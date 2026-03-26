# Scheduling API Improvements – Friendlier & Less Error-Prone

This document proposes backend API changes to make scheduling data easier to consume and reduce frontend parsing errors (e.g. Gantt overlap display, wrong `job_id` on slots).

---

## 1. Current Pain Points

| Issue | Impact |
|-------|--------|
| **Two shapes for proposals** | Batch returns `proposed_slots` at top level; persisted proposals return `proposal_json` (string). Frontend must branch parsing logic. |
| **`job_id` on proposal only** | Slots don't include `job_id`. Easy to forget when flattening; causes wrong labels or grouping. |
| **No canonical "slots for Gantt" endpoint** | Frontend must flatten proposals or fetch slots from multiple sources. |
| **Inconsistent nesting** | `GET /proposals/:id` returns decoded proposal; `GET /jobs/:id/proposals` returns raw records with `proposal_json` string. |
| **Verify-overlaps needs two modes** | `scope: proposals` vs `scope: applied` with different input shapes; easy to misuse. |

---

## 2. Proposed Improvements

### 2.1 Single Gantt-Oriented Endpoint

**Add:** `GET /ai/scheduling/gantt-data` or `GET /ai/scheduling/schedule-for-display`

Returns a **canonical, flat shape** ready for Gantt rendering. No parsing branches.

**Response:**
```json
{
  "success": true,
  "data": {
    "source": "proposals",
    "jobs": [
      {
        "job_id": "JOB-SEED-001",
        "product_id": "P-001",
        "proposal_id": "AIPROP-xxx",
        "slots": [
          {
            "job_id": "JOB-SEED-001",
            "job_step_id": "JS-SEED-001-1",
            "machine_id": "M-CNC-01",
            "machine_name": "CNC Mill 01",
            "scheduled_start": "2026-03-09T21:28:58+08:00",
            "scheduled_end": "2026-03-10T09:58:58+08:00",
            "step_name": "CNC Rough Milling"
          }
        ]
      }
    ],
    "verify_result": {
      "valid": true,
      "overlap_count": 0
    }
  }
}
```

**Query params:**
- `source`: `"proposals"` (default) | `"applied"` – use proposals or applied slots
- `job_ids`: optional – filter to specific jobs

**Benefits:**
- One endpoint for Gantt; no flattening or branching
- Every slot has `job_id`; no confusion
- Optional built-in overlap check
- Same shape regardless of source

---

### 2.2 Standardize Proposal Shape Everywhere

**Change:** Ensure all proposal-returning endpoints use the **same decoded shape**:

- `POST /batch-proposals`, `POST /reschedule-all`: already return `{ proposal_id, job_id, proposed_slots, ... }`
- `GET /jobs/:id/proposals`: today returns raw `AIProposal` records with `proposal_json` string

**Proposal:** When returning proposals, always expose **decoded** `proposed_slots` (and other proposal fields) at the top level, not inside `proposal_json`.

**Example – `GET /jobs/:id/proposals` response:**
```json
{
  "success": true,
  "data": [
    {
      "proposal_id": "AIPROP-xxx",
      "job_id": "JOB-SEED-001",
      "status": "draft",
      "proposed_slots": [...],
      "earliest_start": "...",
      "estimated_completion": "..."
    }
  ]
}
```

**No `proposal_json` string for consumers** – keep it internal; frontend only uses decoded fields.

---

### 2.3 Add `job_id` to Each Slot

**Change:** Include `job_id` on every slot in all API responses.

**Slots today:**
```json
{ "job_step_id": "...", "machine_id": "...", "scheduled_start": "...", "scheduled_end": "..." }
```

**Slots after:**
```json
{ "job_id": "JOB-SEED-001", "job_step_id": "...", "machine_id": "...", "scheduled_start": "...", "scheduled_end": "..." }
```

**Endpoints to update:**
- Batch/reschedule proposals
- `GET /proposals/:id`
- `GET /jobs/:id/slots` (applied)
- Gantt endpoint (when added)

**Benefits:** Flattening and grouping are trivial; no risk of missing `job_id`.

---

### 2.4 Simplify Verify-Overlaps Input

**Current:**
- `scope: proposals`: needs `proposal_ids` OR `proposals` (inline)
- `scope: applied`: needs nothing (or optional `job_ids`)

**Proposal:** Add a convenience mode that accepts **any list of slots** and verifies them:

```
POST /ai/scheduling/verify-overlaps
{
  "slots": [
    { "job_id": "JOB-1", "machine_id": "M-CNC-01", "scheduled_start": "...", "scheduled_end": "..." }
  ]
}
```

Frontend can send whatever it has (e.g. flattened slots from proposals) without converting to `proposal_ids` or full proposals. Same response shape.

---

### 2.5 Consistent Response Wrapper

**Standard shape:**
```json
{
  "success": true,
  "data": { ... },
  "meta": {
    "source": "proposals",
    "total_slots": 60,
    "overlap_count": 0
  }
}
```

Optional `meta` for overlap checks and source info, so the frontend can show "Verified: 0 overlaps" without extra calls.

---

## 3. Implementation Priority

| Change | Effort | Impact |
|--------|--------|--------|
| Add `job_id` to each slot | Low | High – removes main parsing pitfall |
| Gantt-oriented endpoint | Medium | High – single source for display |
| Standardize `GET /jobs/:id/proposals` to decoded shape | Medium | Medium – one less parsing branch |
| Verify-overlaps `slots` input | Low | Medium – easier verification |

---

## 4. Migration Notes

- **Additive changes:** New fields (`job_id` on slots) and new endpoints are backward-compatible.
- **Deprecation:** If `proposal_json` is removed from public API responses, give advance notice; keep it in DB for internal use.
- **Frontend:** Can migrate gradually – first use `job_id` on slots, then switch to Gantt endpoint when ready.

---

## 5. Updated SCHEDULING_API_REFERENCE.md

When these changes are implemented, update `SCHEDULING_API_REFERENCE.md` to:

1. Document the new Gantt endpoint
2. Show the canonical slot shape with `job_id`
3. Describe the verify-overlaps `slots` input
4. Add a "Recommended for Gantt" section pointing to the Gantt endpoint and standardized slot shape
