# Scheduling Settings — Frontend Implementation Guide

Single reference for implementing the **Scheduling** section on the Settings page.

---

## API

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/v1/scheduling/settings` | Fetch all scheduling settings |
| PUT | `/api/v1/scheduling/settings` | Update scheduling settings |
| POST | `/api/v1/scheduling/refresh-work-calendars` | Apply work template to resource/machine calendars |

---

## GET Response

```json
{
  "success": true,
  "data": {
    "lock_in_window_minutes": 240,
    "deviation_penalty_weight": 0.25,
    "split_strategy": "equal",
    "objective": "minimize_tardiness",
    "auto_reschedule_on_event": false,
    "work_start_time": "08:00",
    "work_end_time": "17:00",
    "work_days": "1,2,3,4,5",
    "public_holidays": ["2026-01-01", "2026-12-25"],
    "updated_at": "2026-03-19T12:00:00Z"
  }
}
```

---

## PUT Request (all fields optional)

```json
{
  "lock_in_window_minutes": 240,
  "deviation_penalty_weight": 0.25,
  "split_strategy": "equal",
  "objective": "minimize_tardiness",
  "auto_reschedule_on_event": true,
  "work_start_time": "08:00",
  "work_end_time": "17:00",
  "work_days": "1,2,3,4,5",
  "public_holidays": ["2026-01-01", "2026-12-25"]
}
```

---

## Field Reference

| Field | Type | UI Control | Validation |
|-------|------|------------|------------|
| `lock_in_window_minutes` | int | Number input | 0–1440 |
| `deviation_penalty_weight` | float | Number input | 0–5 |
| `split_strategy` | string | Dropdown | `equal`, `proportional`, `manual`, `min_time`, `priority` |
| `objective` | string | Dropdown | `minimize_tardiness`, `minimize_makespan`, `balance_load`, `maximize_utilization` |
| `auto_reschedule_on_event` | bool | Toggle | — |
| **`work_start_time`** | string | **Time input** | HH:MM (24h), e.g. `"08:00"` |
| **`work_end_time`** | string | **Time input** | HH:MM (24h), e.g. `"17:00"`. Must be after `work_start_time` |
| **`work_days`** | string | **Checkboxes or multi-select** | Comma-separated `0–6`: 0=Sun, 1=Mon, …, 6=Sat. Mon–Fri = `"1,2,3,4,5"`; +Sat = `"1,2,3,4,5,6"` |
| **`public_holidays`** | string[] | **Date picker list** | YYYY-MM-DD dates. Add/remove; empty array = none |

---

## UI to Add (not yet implemented)

### 1. Work start time
- **Label:** "Work start time"
- **Control:** `<input type="time" />` or time picker (24h)
- **Value:** `work_start_time` (e.g. `"08:00"`)
- **Hint:** "Daily shift start (24h)"

### 2. Work end time
- **Label:** "Work end time"
- **Control:** `<input type="time" />` or time picker (24h)
- **Value:** `work_end_time` (e.g. `"17:00"`)
- **Hint:** "Daily shift end (24h). Must be after start."
- **Validation:** End ≥ Start

### 3. Workdays (Mon–Sat)
- **Label:** "Workdays"
- **Control:** Checkboxes for Mon, Tue, Wed, Thu, Fri, Sat (Sun optional)
- **Value:** Map to `work_days` string:
  - Mon–Fri checked → `"1,2,3,4,5"`
  - Mon–Sat checked → `"1,2,3,4,5,6"`
  - Mapping: Sun=0, Mon=1, Tue=2, Wed=3, Thu=4, Fri=5, Sat=6

### 4. Public holidays
- **Label:** "Public holidays"
- **Control:** List of dates with add/remove. Date picker for new dates.
- **Value:** `public_holidays` array, e.g. `["2026-01-01", "2026-12-25"]`
- **Hint:** "Dates when no work is scheduled"

---

## Data Flow

1. **On load:** `GET /api/v1/scheduling/settings` → populate all form fields
2. **On save:** Collect form values → `PUT /api/v1/scheduling/settings` with changed fields
3. **After changing work times/workdays/holidays:** Optionally show a "Refresh work calendars" button that calls `POST /api/v1/scheduling/refresh-work-calendars` to apply the new template

---

## Example: Work days mapping

```javascript
// work_days string → checkboxes
const workDaysToCheckboxes = (str) => {
  const nums = (str || "1,2,3,4,5").split(",").map(s => parseInt(s.trim(), 10));
  return { mon: nums.includes(1), tue: nums.includes(2), wed: nums.includes(3), thu: nums.includes(4), fri: nums.includes(5), sat: nums.includes(6), sun: nums.includes(0) };
};

// checkboxes → work_days string
const checkboxesToWorkDays = (cb) => {
  const days = [];
  if (cb.sun) days.push(0);
  if (cb.mon) days.push(1);
  if (cb.tue) days.push(2);
  if (cb.wed) days.push(3);
  if (cb.thu) days.push(4);
  if (cb.fri) days.push(5);
  if (cb.sat) days.push(6);
  return days.sort((a, b) => a - b).join(",");
};
```

---

## Error Handling

| Error | Cause |
|-------|-------|
| `work_start_time must be HH:MM (24h)` | Invalid time format |
| `work_start_time must be before work_end_time` | Start ≥ End |
| `work_days must be comma-separated 0-6...` | Invalid work days format |

Display via `toast.error()` or inline validation.
