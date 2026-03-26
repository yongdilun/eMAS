# Scheduling API Reference

All schedule-related APIs with parameters, usage, and examples.

**Base URL:** `http://localhost:8080/api/v1`  
**Headers:** `Content-Type: application/json`, `X-User-Role: planner` (for write operations)

---

## 1. AI Proposal Generation

### POST /ai/scheduling/batch-proposals

Generate and persist AI proposals for multiple jobs in one batch. Jobs are scheduled with shared machine state.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_ids` | string[] | No* | Explicit job IDs to schedule |
| `scope` | string | No* | `"all_unscheduled"` = all planned/scheduled jobs with no active slots |
| `order_by` | string | No | `"epo"` (default), `"edd"`, `"fifo"`, or `"readiness"` |

*Provide either `job_ids` or `scope: "all_unscheduled"`.

**Example:**
```json
POST /api/v1/ai/scheduling/batch-proposals
{
  "scope": "all_unscheduled",
  "order_by": "readiness"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "proposals": [
      {
        "proposal_id": "AIPROP-xxx",
        "job_id": "JOB-SEED-001",
        "proposed_slots": [...],
        "earliest_start": "2026-03-09T19:09:57+08:00",
        "estimated_completion": "2026-03-10T01:24:57+08:00"
      }
    ],
    "summary": { "generated": 12, "blocked": 0, "skipped": 0 }
  }
}
```

---

### POST /ai/scheduling/reschedule-all

Cancel all active slots, delete proposals, then regenerate from scratch for all planned/scheduled jobs.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_by` | string | No | `"epo"` (default), `"edd"`, `"fifo"`, or `"readiness"` |

**Example:**
```json
POST /api/v1/ai/scheduling/reschedule-all
{
  "order_by": "readiness"
}
```

**Response:** Same as batch-proposals.

---

### POST /ai/scheduling/jobs/:id/proposals

Generate and persist a single AI proposal for one job.

**Path:** `id` = job ID

**Example:**
```json
POST /api/v1/ai/scheduling/jobs/JOB-SEED-001/proposals
{}
```

**Response (201):** SchedulingProposal with `proposal_id`, `status: "draft"`, etc.

---

### GET /ai/scheduling/jobs/:id/proposal

Get the latest draft proposal for a job (without persisting). Used for preview before generate.

**Path:** `id` = job ID

**Example:**
```http
GET /api/v1/ai/scheduling/jobs/JOB-SEED-001/proposal
```

---

## 2. Verify Overlaps

### POST /ai/scheduling/verify-overlaps

Check that no two slots use the same machine at overlapping times.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `proposal_ids` | string[] | No* | Proposal IDs to fetch from DB and verify |
| `proposals` | array | No* | Inline proposals (e.g. from batch response) |
| `scope` | string | No | `"proposals"` (default) or `"applied"` |
| `job_ids` | string[] | No | When scope=`"applied"`, limit to these jobs; empty = all |

*For scope=`"proposals"`: provide `proposal_ids` or `proposals`. For scope=`"applied"`: no proposals needed.

**Example (proposals by ID):**
```json
POST /api/v1/ai/scheduling/verify-overlaps
{
  "proposal_ids": ["AIPROP-xxx", "AIPROP-yyy"],
  "scope": "proposals"
}
```

**Example (verify applied slots – what Gantt shows):**
```json
POST /api/v1/ai/scheduling/verify-overlaps
{
  "scope": "applied"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "valid": true,
    "total_slots": 60,
    "overlap_count": 0,
    "overlaps": []
  }
}
```

---

## 3. Proposal Lifecycle (CRUD, Approve, Reject, Apply)

### GET /ai/scheduling/jobs/:id/proposals

List all persisted proposals for a job, newest first.

**Path:** `id` = job ID

**Example:**
```http
GET /api/v1/ai/scheduling/jobs/JOB-SEED-001/proposals
```

---

### GET /ai/scheduling/proposals/:id

Get one proposal by ID.

**Path:** `id` = proposal ID

**Example:**
```http
GET /api/v1/ai/scheduling/proposals/AIPROP-12e7480d
```

---

### POST /ai/scheduling/proposals/:id/approve

Approve a draft proposal so it can be applied.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `notes` | string | No | Planner notes |

**Example:**
```json
POST /api/v1/ai/scheduling/proposals/AIPROP-xxx/approve
{
  "notes": "Approved for production"
}
```

---

### POST /ai/scheduling/proposals/:id/reject

Reject a proposal with reason.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `reason` | string | No | Rejection reason |

**Example:**
```json
POST /api/v1/ai/scheduling/proposals/AIPROP-xxx/reject
{
  "reason": "Machine M-CNC-02 unavailable"
}
```

---

### POST /ai/scheduling/proposals/:id/apply

Apply an approved proposal: creates slots in `job_step_schedule_slots`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `idempotency_key` | string | No | Safe retry key (same key returns same result) |

**Example:**
```json
POST /api/v1/ai/scheduling/proposals/AIPROP-xxx/apply
{
  "idempotency_key": "apply-20260309-001"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "proposal_id": "AIPROP-xxx",
    "job_id": "JOB-SEED-001",
    "applied_at": "2026-03-09T14:30:00Z",
    "applied_slot_count": 5,
    "created_slots": ["SLOT-abc", "SLOT-def", ...]
  }
}
```

---

## 4. AI Assist & Analysis

### GET /ai/scheduling/jobs/:id/assist

Combined AI assist: readiness, solver preview, estimated completion, delay risk, split suggestions.

**Path:** `id` = job ID

**Example:**
```http
GET /api/v1/ai/scheduling/jobs/JOB-SEED-001/assist
```

---

### GET /ai/scheduling/jobs/:id/delay-risk

Delay risk evaluation for one job.

**Path:** `id` = job ID

**Example:**
```http
GET /api/v1/ai/scheduling/jobs/JOB-SEED-001/delay-risk
```

---

### GET /ai/scheduling/jobs/:id/explanation

Planner-readable explanation and recommended actions for a job.

**Path:** `id` = job ID

**Example:**
```http
GET /api/v1/ai/scheduling/jobs/JOB-SEED-001/explanation
```

---

## 5. Step-Level Support

### GET /ai/scheduling/job-steps/:id/split-suggestion

Split recommendation for a job step (serial vs parallel, allocation %).

**Path:** `id` = job step ID

**Example:**
```http
GET /api/v1/ai/scheduling/job-steps/JS-SEED-001-1/split-suggestion
```

---

### GET /ai/scheduling/job-steps/:id/machine-ranking

Ranked candidate machines for a job step in a time window.

| Query Param | Type | Required | Description |
|-------------|------|----------|-------------|
| `start` | string | Yes | RFC3339 start |
| `end` | string | Yes | RFC3339 end |

**Example:**
```http
GET /api/v1/ai/scheduling/job-steps/JS-SEED-001-1/machine-ranking?start=2026-03-09T08:00:00%2B08:00&end=2026-03-10T08:00:00%2B08:00
```

---

## 6. Bottleneck Forecast

### GET /ai/scheduling/bottleneck-forecast

Machine-level bottleneck forecast for upcoming days.

| Query Param | Type | Required | Description |
|-------------|------|----------|-------------|
| `days_ahead` | integer | No | Forecast horizon (default: 7) |

**Example:**
```http
GET /api/v1/ai/scheduling/bottleneck-forecast?days_ahead=5
```

---

## 7. Low-Level Scheduling APIs

### GET /scheduling/products/:id/readiness

Material and sub-product readiness for scheduling.

| Query Param | Type | Required | Description |
|-------------|------|----------|-------------|
| `quantity` | number | No | Quantity (default: 1) |

**Example:**
```http
GET /api/v1/scheduling/products/P-001/readiness?quantity=500
```

---

### GET /scheduling/products/:id/explosion

Recursive material and sub-product demand explosion.

| Query Param | Type | Required | Description |
|-------------|------|----------|-------------|
| `quantity` | number | No | Quantity (default: 1) |

**Example:**
```http
GET /api/v1/scheduling/products/P-001/explosion?quantity=500
```

---

### GET /scheduling/steps/:id/candidate-machines

Capable machines ranked by availability and efficiency.

| Query Param | Type | Required | Description |
|-------------|------|----------|-------------|
| `start` | string | Yes | RFC3339 start |
| `end` | string | Yes | RFC3339 end |

**Example:**
```http
GET /api/v1/scheduling/steps/STP-P001-1/candidate-machines?start=2026-03-09T08:00:00%2B08:00&end=2026-03-10T08:00:00%2B08:00
```

---

### POST /scheduling/slots/validate

Validate one candidate slot before creating it.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_step_id` | string | Yes | Job step ID |
| `machine_id` | string | Yes | Machine ID |
| `scheduled_start` | string | Yes | RFC3339 start |
| `scheduled_end` | string | Yes | RFC3339 end |
| `quantity` | integer | Yes | Quantity |
| `exclude_slot_id` | string | No | When validating an update |

**Example:**
```json
POST /api/v1/scheduling/slots/validate
{
  "job_step_id": "JS-SEED-001-1",
  "machine_id": "M-CNC-02",
  "scheduled_start": "2026-03-09T08:00:00+08:00",
  "scheduled_end": "2026-03-09T09:30:00+08:00",
  "quantity": 500
}
```

**Response:** `{ "valid": true, "reasons": [] }`

---

### GET /scheduling/jobs/:id/earliest-completion

Estimate earliest completion time for a job using readiness, machines, and slot occupancy.

**Path:** `id` = job ID

**Example:**
```http
GET /api/v1/scheduling/jobs/JOB-SEED-001/earliest-completion
```

---

### GET /scheduling/jobs/:id/solver-preview

Solver-ready problem preview for one job (steps, candidates, constraints).

**Path:** `id` = job ID

**Example:**
```http
GET /api/v1/scheduling/jobs/JOB-SEED-001/solver-preview
```

---

## 8. Common Flow Examples

### Generate schedule for all unscheduled jobs
```json
POST /ai/scheduling/batch-proposals
{ "scope": "all_unscheduled", "order_by": "epo" }
```

### Verify no overlaps (proposals)
```json
POST /ai/scheduling/verify-overlaps
{ "proposal_ids": ["AIPROP-1", "AIPROP-2"], "scope": "proposals" }
```

### Approve and apply a proposal
```json
POST /ai/scheduling/proposals/AIPROP-xxx/approve
{ "notes": "OK" }

POST /ai/scheduling/proposals/AIPROP-xxx/apply
{}
```

### Reschedule everything and verify
```json
POST /ai/scheduling/reschedule-all
{ "order_by": "readiness" }

POST /ai/scheduling/verify-overlaps
{ "scope": "applied" }
```

---

## 9. order_by Values

| Value | Description |
|-------|-------------|
| `epo` | Earliest priority order: priority (high→low), then deadline |
| `edd` | Earliest due date: deadline first |
| `fifo` | First in, first out: creation time |
| `readiness` | Earliest ready first: jobs that can start now first |
