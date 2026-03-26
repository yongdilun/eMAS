# Scheduling Gaps – API Changes & Additions

API changes and new endpoints introduced by the scheduling gaps implementation. Use this guide when integrating frontend or external systems.

**Base URL:** `http://localhost:8080/api/v1`  
**Related:** `FRONTEND_SCHEDULING_API.md`, `SCHEDULING_API_REFERENCE.md`

---

## 1. New Endpoint: Emit Scheduling Event

**POST** `/scheduling/events`

Emits a scheduling event (e.g. machine_down, job_delay, urgent_insert). Events are persisted and can trigger automatic rescheduling when `AI_AUTO_RESCHEDULE_ON_EVENT=true`.

### Request

```json
{
  "type": "machine_down",
  "payload": "{\"machine_id\":\"M-CNC-01\",\"down_until\":\"2026-03-22T18:00:00Z\"}"
}
```

| Field    | Type   | Required | Description |
|----------|--------|----------|-------------|
| `type`   | string | Yes      | One of: `machine_down`, `job_delay`, `urgent_insert` |
| `payload`| string | No       | JSON string with event-specific data |

### Response

```json
{
  "success": true,
  "data": {
    "message": "event emitted"
  }
}
```

### Usage

- Call when MES reports a machine down, job delayed, or urgent insert.
- When `AI_AUTO_RESCHEDULE_ON_EVENT` is enabled, a reschedule runs automatically after the event is stored.
- Otherwise, call `POST /ai/scheduling/reschedule-all` manually after emitting events.

---

## 2. Updated: Validate Slot Response

**POST** `/scheduling/slots/validate`

The response now includes structured validation reasons with hard/soft classification and penalties for tie-breaking.

### Request (unchanged)

```json
{
  "job_step_id": "JS-SEED-001-1",
  "machine_id": "M-CNC-02",
  "scheduled_start": "2026-03-09T08:00:00+08:00",
  "scheduled_end": "2026-03-09T09:30:00+08:00",
  "quantity": 500,
  "exclude_slot_id": ""
}
```

### Response (updated)

```json
{
  "success": true,
  "data": {
    "valid": false,
    "job_step_id": "JS-SEED-001-1",
    "machine_id": "M-CNC-02",
    "scheduled_start": "2026-03-09T08:00:00+08:00",
    "scheduled_end": "2026-03-09T09:30:00+08:00",
    "reasons": [
      "slot overlaps machine downtime",
      "machine blocked by tentative slots from other jobs in batch"
    ],
    "validation_reasons": [
      {
        "message": "slot overlaps machine downtime",
        "type": "hard",
        "penalty": 0
      },
      {
        "message": "machine blocked by tentative slots from other jobs in batch",
        "type": "soft",
        "penalty": 10
      }
    ],
    "hard_reasons": ["slot overlaps machine downtime"],
    "soft_reasons": ["machine blocked by tentative slots from other jobs in batch"],
    "total_penalty": 10
  }
}
```

| New field            | Type    | Description |
|----------------------|---------|-------------|
| `validation_reasons` | array   | Each item: `message`, `type` (hard/soft), `penalty` |
| `hard_reasons`       | string[]| Messages for blocking issues (e.g. machine offline, overlap) |
| `soft_reasons`       | string[]| Messages for non-blocking issues (e.g. outside preferred window) |
| `total_penalty`      | number  | Sum of soft-reason penalties; use for tie-breaking candidates |

- `valid` is `false` if any **hard** reason exists.
- Use `hard_reasons` for error messages; use `soft_reasons` and `total_penalty` when choosing between multiple invalid candidates.

---

## 3. Slot Model Extensions (GET / PATCH)

Slots now include `actual_start`, `actual_end`, and support status `paused`.

### Slot object (GET `/slots/:id`, GET `/jobs/:id/slots`, etc.)

| New field       | Type    | Description |
|-----------------|---------|-------------|
| `actual_start`  | string? | RFC3339. Actual start time when production began. |
| `actual_end`    | string? | RFC3339. Actual end time when slot completed. |

### Slot status values

| Status       | Description |
|--------------|-------------|
| `planned`    | Scheduled, not started |
| `running`    | In progress |
| `completed`  | Finished |
| `cancelled`  | Cancelled |
| `paused`     | **New.** Temporarily paused; still blocks the machine. |

### PATCH `/slots/:id` (UpdateSlotRequest)

To support production logging and outcome capture, extend the update request to accept:

| Field          | Type    | Description |
|----------------|---------|-------------|
| `actual_start` | string? | RFC3339. Set when production starts. |
| `actual_end`   | string? | RFC3339. Set when slot completes. |
| `status`       | string? | `planned`, `running`, `completed`, `paused`, `cancelled`. |

*Note: If the backend `UpdateSlotRequest` DTO does not yet include these fields, they can be added to support production log / outcome capture.*

---

## 4. Environment Variables (Feature Flags)

| Variable                       | Default              | Description |
|--------------------------------|----------------------|-------------|
| `AI_SPLIT_STRATEGY`            | `equal`              | Split strategy: `equal`, `min_time`, `priority`. |
| `AI_OBJECTIVE`                 | `minimize_tardiness` | Optimization: `minimize_tardiness`, `minimize_makespan`, `maximize_utilization`. |
| `AI_AUTO_RESCHEDULE_ON_EVENT`  | `false`              | When `true`, `POST /scheduling/events` triggers an automatic reschedule. |

---

## 5. Summary of API Changes

| Area              | Change |
|-------------------|--------|
| **New**           | `POST /scheduling/events` – emit scheduling events |
| **Validate slot** | Response: `validation_reasons`, `hard_reasons`, `soft_reasons`, `total_penalty` |
| **Slot**          | Response: `actual_start`, `actual_end`; status `paused` supported |
| **Config**        | `AI_SPLIT_STRATEGY`, `AI_OBJECTIVE`, `AI_AUTO_RESCHEDULE_ON_EVENT` |

---

## 6. Backward Compatibility

- `reasons` in ValidateSlot remains a flat list of messages (unchanged).
- Existing slot consumers can ignore `actual_start`, `actual_end` if not used.
- New env vars default to prior behaviour; no breaking changes.
