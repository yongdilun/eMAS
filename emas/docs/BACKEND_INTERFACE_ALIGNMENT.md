# Backend Interface Alignment

Backend changes required to align with the frontend interface design (`INTERFACE_DESIGN.md`). This document lists expectations from the interface that the backend does not yet fully support, with concrete implementation guidance.

**Implementation status:** Gaps 1–7 implemented (2026-03-19). See `FRONTEND_INTEGRATION_MESSAGE.md` for frontend integration details.

**Related:** `INTERFACE_DESIGN.md`, `SCHEDULING_GAPS_API_CHANGELOG.md`, `SCHEDULING_GAPS_FRONTEND_IMPROVEMENTS.md`, `FRONTEND_INTEGRATION_MESSAGE.md`

---

## Summary

| # | Gap | Priority | Status |
|---|-----|----------|--------|
| 1 | Process step materials API | High | **Done** |
| 2 | UpdateSlot: actual_start, actual_end, status | High | **Done** |
| 3 | SlotResponse / JobResponse slots: actual_start, actual_end | Medium | **Done** |
| 4 | Record Downtime → scheduling event integration | Medium | **Done** (Option A) |
| 5 | Scheduling events: documented payload shapes | Medium | **Done** (validated) |
| 6 | Scheduling settings: split strategy, objective, auto-reschedule | Medium | **Done** |
| 7 | Log Production: Downtime (mins) field | Low | **Done** |
| 8 | Explosion API: by_step variant | Low | Omitted (Gap 1 sufficient) |

---

## 1. Process Step Materials API (High)

**Interface expectation:** Section 2.1, 5.5, 7 — "Materials per step" expandable in JobDetailsPanel and Scheduling Preview. Primary data source: `GET /process-steps/:step_id/materials`.

**Current state:** No HTTP endpoint. `ProcessStepMaterialRepository` has `ListInputsByStepID(stepID)` and `ListByStepID(stepID)`.

**Required change:**

- **Add endpoint:** `GET /api/v1/process-steps/:step_id/materials`
- **Response:** Array of ProcessStepMaterial records (filtered to inputs only for display; optionally expose outputs for other use cases).
- **Suggested response shape:**
  ```json
  {
    "success": true,
    "data": [
      {
        "material_id": "MAT-001",
        "product_id": "",
        "role": "input",
        "quantity_per_unit": 2.5,
        "unit": "kg"
      }
    ]
  }
  ```
- **Implementation:** New handler in process handler or dedicated handler; wire `ProcessStepMaterialRepository.ListInputsByStepID` (or `ListByStepID` with frontend filtering). Add route: `v1.GET("/process-steps/:step_id/materials", ...)`.

**Note:** The router uses `/processes/:id/steps` for process steps. Process *steps* have `step_id`. The interface refers to `step_id` (the process step’s ID). Ensure the route clearly distinguishes process vs process-step. Suggested: `GET /api/v1/process-steps/:step_id/materials` where `:step_id` is the process step ID (e.g. `PS-001`).

---

## 2. UpdateSlot: actual_start, actual_end, status (High)

**Interface expectation:** Section 2.1 — Slot cards with "Start", "Pause", "Resume"; production logging and actual times.

**Current state:** `UpdateSlotRequest` (dto.go) includes: `MachineID`, `ScheduledStart`, `ScheduledEnd`, `QuantityPlanned`, `AllocationPercent`, `IsParallel`, `BatchSequence`. Domain `JobStepScheduleSlots` has `ActualStart`, `ActualEnd`, `Status` (including `SlotStatusPaused`). `JobSlotService.UpdateSlot` does not handle `actual_start`, `actual_end`, or `status` for Pause/Resume.

**Required change:**

- **Extend `UpdateSlotRequest`** with:
  ```go
  ActualStart *time.Time `json:"actual_start"`
  ActualEnd   *time.Time `json:"actual_end"`
  Status      *string    `json:"status"`
  ```
- **Extend `JobSlotService.UpdateSlot`** to apply these fields when provided.
- **Validation:** If `Status` is set, allow only: `planned`, `running`, `paused`, `completed`, `cancelled`. When setting `status` to `running`, optionally set `actual_start` to now if not provided. When setting `status` to `completed`, optionally set `actual_end` to now if not provided.
- **Frontend mapping:** Start → `status: "running"`, `actual_start: now`; Pause → `status: "paused"`; Resume → `status: "running"`; Complete → `status: "completed"`, `actual_end: now`.

---

## 3. SlotResponse / JobResponse slots: actual_start, actual_end (Medium)

**Interface expectation:** Section 2.1 — Slot cards show actual times; Gantt may show actual vs planned.

**Current state:** Direct slot endpoints (`GET /slots/:id`, `GET /job-steps/:id/slots`, etc.) return `domain.JobStepScheduleSlots` which includes `actual_start`, `actual_end` in JSON. `SlotResponse` (used in `JobResponse.Slots`) does **not** include these fields. Any API that returns jobs with embedded slots and uses `SlotResponse` will omit actual times.

**Required change:**

- **Extend `SlotResponse`** (dto.go) with:
  ```go
  ActualStart *time.Time `json:"actual_start,omitempty"`
  ActualEnd   *time.Time `json:"actual_end,omitempty"`
  ```
- **Ensure** all code that builds `JobResponse` (or similar) and populates `Slots` maps these fields from the domain to `SlotResponse`.

---

## 4. Record Downtime → Scheduling Event Integration (Medium)

**Interface expectation:** Section 1.2 — RecordDowntimeModal from Machine Resources and JobDetailsPanel. Expectation: downtime affects schedule and may trigger reschedule.

**Current state:** `POST /api/v1/machines/downtime` records downtime in `machine_downtime`. Scheduler validates slots against downtimes. `POST /api/v1/scheduling/events` with `type: "machine_down"` creates a scheduling event and, when `AI_AUTO_RESCHEDULE_ON_EVENT` is true, triggers `RescheduleAll`. These are separate flows.

**Gap:** Recording downtime via `/machines/downtime` does **not** emit a scheduling event. If auto-reschedule on events is desired when downtime is recorded, the frontend would need to call both; that is brittle and not documented.

**Required change (choose one):**

- **Option A (recommended):** When `RecordDowntime` succeeds, optionally emit a `machine_down` scheduling event with payload `{"machine_id": "...", "start_time": "...", "end_time": "..."}`. Use a feature flag or config (e.g. `AI_EMIT_EVENT_ON_DOWNTIME`) to avoid duplicate events if the frontend also calls `/scheduling/events`.
- **Option B:** Document that the frontend must call both `POST /machines/downtime` and `POST /scheduling/events` (type `machine_down`) when recording downtime from the scheduling flow. Define the payload format for `machine_down`.

**Payload convention for `machine_down` (for Option A or B):**
```json
{
  "machine_id": "M-001",
  "start_time": "2026-03-19T10:00:00Z",
  "end_time": "2026-03-19T12:00:00Z"
}
```

---

## 5. Scheduling Events: Documented Payload Shapes (Medium)

**Interface expectation:** Section 1.3, 1.4 — Report Delay (Reason, Delay in minutes); Urgent Insert (Reason, Priority High/Critical). Both need clear backend expectations.

**Current state:** `POST /scheduling/events` accepts `type` and `payload` (string). Payload is stored as-is; no schema enforced.

**Required change:**

Define and document the payload format for each event type so the frontend can send consistent data.

| Type | Payload (JSON string) | Fields |
|------|-----------------------|--------|
| `machine_down` | `{"machine_id":"M-001","start_time":"...","end_time":"..."}` | `machine_id`, `start_time`, `end_time` (ISO8601) |
| `job_delay` | `{"job_id":"JOB-001","delay_minutes":60,"reason":"..."}` | `job_id` (required), `delay_minutes` (required), `reason` (optional) |
| `urgent_insert` | `{"job_id":"JOB-001","priority":"high","reason":"..."}` | `job_id` (required), `priority` ("high"\|"critical"), `reason` (optional) |

- Add validation (or at least documentation) so consumers (AI, rescheduler) can rely on these fields.
- EmitSchedulingEvent can parse and validate payload; reject malformed payloads with 400.

---

## 6. Scheduling Settings: Split Strategy, Objective, Auto-Reschedule (Medium)

**Interface expectation:** Section 3.1 — Settings page has "Scheduling" section: Split Strategy, Optimization Objective, Auto-reschedule on Events.

**Current state:** `GET/PUT /api/v1/scheduling/settings` supports only `lock_in_window_minutes` and `deviation_penalty_weight`. Split strategy, optimization objective, and auto-reschedule are controlled by env vars / feature flags (`AI_SPLIT_STRATEGY`, `AI_OBJECTIVE`, `AI_AUTO_RESCHEDULE_ON_EVENT`).

**Required change:**

- **Extend `SchedulingSettingsResponse`** and **`UpdateSchedulingSettingsRequest`** with:
  - `split_strategy` (string): e.g. `"equal"`, `"proportional"`, `"manual"`
  - `optimization_objective` (string): e.g. `"minimize_tardiness"`, `"minimize_makespan"`, `"balance_load"`
  - `auto_reschedule_on_events` (bool)
- **Persist** these in `system_settings` (or equivalent) via `SystemSettingsRepository`.
- **Wire** these settings into the AI scheduling service / feature flags so runtime behavior uses DB values when present, with env vars as fallback.
- **Alternative:** Document that these remain env-only; frontend Settings would show them as read-only with a note that they are configured server-side.

---

## 7. Log Production: Downtime (mins) Field (Low)

**Interface expectation:** Section 1.6 — Log Production tab includes "Downtime (mins)".

**Current state:** `LogProductionRequest` has: `SlotID`, `StartTime`, `EndTime`, `QuantityProduced`, `QuantityScrap`, `OperatorNotes`. No `downtime_minutes` field.

**Required change (optional):**

- Add `DowntimeMinutes *int` to `LogProductionRequest` and `ProductionLogs` domain if downtime-per-slot is needed for OEE/reporting.
- Alternatively, treat downtime as a separate concept (e.g. `POST /machines/downtime` with `job_step_slot_id`), which is already supported. Document that "Downtime (mins)" in Log Production should either call the downtime API or be deferred.

---

## 8. Explosion API: by_step Variant (Low)

**Interface expectation:** Section 7 — Fallback for materials per step: "Explosion API (by_step)".

**Current state:** `GET /scheduling/products/:id/explosion` returns product-level explosion (materials, sub-products). No `by_step` option or step-indexed output.

**Required change (optional):**

- Add query param `?by_step=true` (or similar) to the explosion endpoint. When set, return materials grouped or keyed by process step ID.
- Or document that materials per step are obtained solely via `GET /process-steps/:step_id/materials`; the explosion API remains product-level only. The interface lists this as a fallback, so implementing the process-step materials endpoint (Gap 1) may be sufficient.

---

## Implementation Order

1. **Process step materials API** (Gap 1) — unblocks materials-per-step UI.
2. **UpdateSlot extensions** (Gap 2) — unblocks Start/Pause/Resume and actual times.
3. **SlotResponse extensions** (Gap 3) — consistent slot data in job responses.
4. **Event payload documentation** (Gap 5) — clear contract for Report Delay and Urgent Insert.
5. **Record Downtime integration** (Gap 4) — optional auto-reschedule on downtime.
6. **Scheduling settings** (Gap 6) — if UI-configurable settings are required.
7. **Log Production downtime** (Gap 7) and **Explosion by_step** (Gap 8) — as needed.

---

## API Reference Addendum

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/process-steps/:step_id/materials` | List materials for a process step (inputs) |
| PUT | `/api/v1/job-steps/slots/:id` | Update slot (extend with `actual_start`, `actual_end`, `status`) |
| POST | `/api/v1/machines/downtime` | Record downtime (optionally emits `machine_down` event) |
| POST | `/api/v1/scheduling/events` | Emit scheduling event; payloads per Gap 5 |
| GET/PUT | `/api/v1/scheduling/settings` | Extend with split_strategy, optimization_objective, auto_reschedule_on_events |
