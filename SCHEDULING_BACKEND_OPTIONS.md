# Scheduling Backend: Reschedule-All Preview

**Status: Implemented** – `dry_run` parameter is now supported.

---

## Behavior

`POST /api/v1/ai/scheduling/reschedule-all` accepts an optional `dry_run` flag:

| `dry_run` | Behavior |
|-----------|----------|
| `true` | Preview only. No cancel, no delete, no persist. Returns proposals without side effects. |
| `false` or omitted | Cancel slots, delete proposals, regenerate, persist. Same as before. |

---

## Request

```http
POST /api/v1/ai/scheduling/reschedule-all
Content-Type: application/json
X-User-Role: planner

{ "order_by": "epo", "dry_run": true }
```

| Field | Type | Description |
|-------|------|--------------|
| `order_by` | string | `"epo"`, `"edd"`, `"fifo"`, or `"readiness"` |
| `dry_run` | boolean | `true` = preview only, no side effects |

---

## Response

Same shape in both modes:

```json
{
  "success": true,
  "data": {
    "proposals": [ /* SchedulingProposal[] */ ],
    "summary": { "generated": 12, "blocked": 0, "skipped": 0 }
  }
}
```

---

## Frontend Flow

1. User clicks "Reschedule All" → modal opens
2. User clicks "Preview" → `POST reschedule-all` with `{"dry_run": true}` → show proposals in Gantt (no side effects)
3. User clicks "Confirm" → `POST reschedule-all` with `{"dry_run": false}` or omit `dry_run` → backend executes
4. User applies proposals to write to job plan
