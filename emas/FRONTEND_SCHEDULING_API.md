# Scheduling API – Frontend Usage Guide

APIs to generate, verify, and display job schedules in the frontend.

**Base URL:** `http://localhost:8080/api/v1`  
**Headers:** `Content-Type: application/json`, `X-User-Role: planner` (for write operations)

> **API changelog (scheduling gaps):** See [`docs/SCHEDULING_GAPS_API_CHANGELOG.md`](docs/SCHEDULING_GAPS_API_CHANGELOG.md) for new endpoints, updated response shapes, and slot model changes from the gaps implementation.  
> **Frontend improvements:** See [`docs/SCHEDULING_GAPS_FRONTEND_IMPROVEMENTS.md`](docs/SCHEDULING_GAPS_FRONTEND_IMPROVEMENTS.md) for detailed UI/UX changes required to support the scheduling gaps.

---

## 1. List Jobs

Fetch jobs (optionally filtered). Use after Apply All to show the scheduled job list with late labels.

```
GET /api/v1/jobs
GET /api/v1/jobs?status=scheduled
GET /api/v1/jobs/:id
```

**Response:** Jobs. When a job has a deadline and active slots (planned/running), the response includes optional `deadline_status`:

| Field | Type | Description |
|-------|------|-------------|
| `deadline_status.is_late` | boolean | true if max(slot.scheduled_end) > job.deadline |
| `deadline_status.late_by` | string | Human-readable: "2 days", "4 hours", or "on time" |

**UI:** Use `job.deadline_status?.is_late` to show a "Late" badge and `job.deadline_status?.late_by` for the label after Apply All.

---

## 2. Generate Batch Proposals (schedule all unscheduled jobs)

Generates AI proposals for all unscheduled jobs and persists them.

**Client timeout:** Use a timeout of at least **30 seconds** (60s for large job sets). Shorter timeouts may cause "context deadline exceeded". On timeout, the API may return 200 with `partial: true` and partial results, or 408 if no proposals were generated yet.

```
POST /api/v1/ai/scheduling/batch-proposals
```

**Request body:**
```json
{
  "scope": "all_unscheduled",
  "order_by": "epo"
}
```

| Field      | Type   | Description |
|-----------|--------|-------------|
| `scope`   | string | `"all_unscheduled"` – all planned/scheduled jobs with no slots |
| `order_by`| string | `"epo"` (default), `"edd"`, `"fifo"`, or `"readiness"` (schedule ready-now jobs first) |

**Response:**
```json
{
  "success": true,
  "data": {
    "proposals": [
      {
        "proposal_id": "AIPROP-xxx",
        "job_id": "JOB-SEED-001",
        "product_id": "P-001",
        "status": "draft",
        "feasible": true,
        "earliest_start": "2026-03-09T19:09:57+08:00",
        "estimated_completion": "2026-03-10T01:24:57+08:00",
        "deadline_status": {
          "deadline": "2026-03-23T17:00:00Z",
          "is_late": true,
          "tardiness_mins": 2460,
          "late_by": "1 day 17 hours"
        },
        "summary": ["Step X was assigned to Machine Y", ...],
        "proposed_slots": [
          {
            "job_step_id": "JS-SEED-001-1",
            "step_name": "CNC Rough Milling",
            "machine_id": "M-CNC-02",
            "machine_name": "CNC Mill 02",
            "scheduled_start": "2026-03-09T19:09:57+08:00",
            "scheduled_end": "2026-03-09T20:39:57+08:00",
            "quantity_planned": 500,
            "estimated_duration_mins": 90
          }
        ]
      }
    ],
    "summary": {
      "generated": 18,
      "blocked": 0,
      "skipped": 0,
      "on_time_count": 12,
      "late_count": 6,
      "late_jobs": [
        { "job_id": "JOB-SEED-015", "tardiness_mins": 2460, "late_by": "1 day 17 hours" }
      ]
    },
    "message": "6 of 18 jobs are estimated to complete after their deadline. Higher-priority jobs were scheduled first; lower-priority jobs may be late."
  }
}
```

| Proposal field | Description |
|----------------|-------------|
| `deadline_status` | Present in batch responses. `is_late` = true when estimated_completion > deadline. Use `late_by` for display. |
| `deadline_status.deadline` | Job's deadline |
| `deadline_status.tardiness_mins` | Minutes past deadline (0 if on time) |
| `deadline_status.late_by` | Human-readable: "45 minutes", "3 hours", "2 days 5 hours" |

| Summary field | Description |
|---------------|-------------|
| `on_time_count` | Proposals that meet deadline |
| `late_count` | Proposals estimated to complete after deadline |
| `late_jobs` | Quick list of late jobs with `job_id`, `tardiness_mins`, `late_by` |

`message` is present when `late_count > 0` to explain that higher-priority jobs were scheduled first.

**Frontend usage for late jobs:**
- Filter: `proposals.filter(p => p.deadline_status?.is_late)`
- Badge: show `p.deadline_status.late_by` (e.g. "Late by 1 day 17 hours")
- Dashboard: use `summary.late_count`
- Compact list: `summary.late_jobs` (no need to scan proposals)

On timeout or cancel, the response may include `"partial": true` and `"message"` in `data`; proposals and summary reflect whatever was generated before the request was cancelled.

---

## 2b. Reschedule All (remove current schedule, regenerate for all jobs)

Cancels all active slots and deletes proposals for planned/scheduled jobs, then regenerates proposals from scratch. Use when you want a full reset and fresh schedule.

**Client timeout:** Same as batch-proposals—use at least **30 seconds** to avoid premature cancellation.

```
POST /api/v1/ai/scheduling/reschedule-all
```

**Request body (optional):**
```json
{
  "order_by": "readiness",
  "dry_run": false
}
```

| Field      | Type    | Description |
|-----------|---------|-------------|
| `order_by`| string  | `"epo"` (default), `"edd"`, `"fifo"`, or `"readiness"` |
| `dry_run` | boolean | `true` = preview only (no cancel/delete); `false` or omit = execute |

**Response:** Same as batch-proposals: `{ proposals, summary }` with `deadline_status` and `on_time_count` / `late_count` / `late_jobs`.

**Frontend flow:** Use `dry_run: true` for "Preview" to show proposals without side effects. Use `dry_run: false` or omit when user confirms.

---

## 3. Verify No Overlaps

Check that no two jobs use the same machine at the same time.

**Gantt displays applied slots** from `job_step_schedule_slots` (status `planned` or `running`). Use `scope: "applied"` to validate the schedule shown on the Gantt. Use `scope: "proposals"` (default) to validate draft proposals before apply.

```
POST /api/v1/ai/scheduling/verify-overlaps
```

**Request body (option A – proposal IDs, scope=proposals):**
```json
{
  "proposal_ids": ["AIPROP-xxx", "AIPROP-yyy", ...],
  "scope": "proposals"
}
```

**Request body (option B – inline proposals):**
```json
{
  "proposals": [ /* data.proposals from batch-proposals */ ],
  "scope": "proposals"
}
```

**Request body (scope=applied – validates job_step_schedule_slots, i.e. what the Gantt shows):**
```json
{
  "scope": "applied",
  "job_ids": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `scope` | string | `"proposals"` (default) – validate `ai_proposals.ProposalJSON`; `"applied"` – validate active slots in `job_step_schedule_slots` |
| `job_ids` | string[] | Optional when scope=`"applied"`. If empty, checks all jobs with active slots |

**Response:**
```json
{
  "success": true,
  "data": {
    "valid": true,
    "total_slots": 42,
    "overlap_count": 0,
    "overlaps": []
  }
}
```

If `valid: false`, use `overlaps` to show which machines have conflicts.

---

## 4. List Proposals for a Job

Show proposals for a specific job (e.g. on a job detail page).

```
GET /api/v1/ai/scheduling/jobs/{job_id}/proposals
GET /api/v1/ai/scheduling/jobs/{job_id}/proposals?include_stale=true
```

| Query param | Default | Description |
|-------------|---------|-------------|
| `include_stale` | `false` | When `false` (default), stale proposals are excluded. Use `true` to include them. |

**Response:** Array of proposals (newest first). Use the latest `status: "draft"` for display. Stale proposals are excluded by default so `loadExistingProposals` won't mix old and new.

---

## 5. Get One Proposal by ID

Fetch full proposal details for display or apply flow.

```
GET /api/v1/ai/scheduling/proposals/{proposal_id}
```

**Example:** `GET /api/v1/ai/scheduling/proposals/AIPROP-12e7480d`

**Response:** Single `SchedulingProposal` with `proposal_id`, `job_id`, `earliest_start`, `estimated_completion`, `proposed_slots`, etc.

---

## 5b. Approve Proposal

When `ProposalApplyRequiresApproval` is enabled, approve before apply.

```
POST /api/v1/ai/scheduling/proposals/{proposal_id}/approve
```

**Request body (optional):**
```json
{
  "notes": "reviewed",
  "skip_staleness_check": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `notes` | string | Optional approval notes. |
| `skip_staleness_check` | boolean | **Use `true` when doing "Apply All"** – same as apply; avoids 409 on proposals 2+ after the first approve/apply changes DB state. |

---

## 6. Apply Proposal

Apply a single proposal to create slots. Approval may be required first (see `ProposalApplyRequiresApproval`).

```
POST /api/v1/ai/scheduling/proposals/{proposal_id}/apply
```

**Request body (optional):**
```json
{
  "idempotency_key": "apply-20260320-001",
  "skip_staleness_check": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `idempotency_key` | string | Optional. Re-apply with same key returns 200 (already applied). |
| `skip_staleness_check` | boolean | **Use `true` when doing "Apply All"** from a batch. Without it, proposal 2+ will fail 409 "stale" because applying proposal 1 changes DB state. |

**Apply All flow:**
1. **Approve all** – For each proposal, `POST .../proposals/{id}/approve` with `{ "skip_staleness_check": true }` when `ProposalApplyRequiresApproval` is enabled.
2. **Apply all** – For each proposal, `POST .../proposals/{id}/apply` with `{ "skip_staleness_check": true }`.

Send `skip_staleness_check: true` for both approve and apply in the batch to avoid 409 staleness errors.

---

## Frontend Flow

### Generate and show schedule

1. Call `POST /ai/scheduling/batch-proposals` with `{"scope":"all_unscheduled"}`.
2. Call `POST /ai/scheduling/verify-overlaps` with `proposal_ids` from `data.proposals`.
3. Show `data.proposals` in a table/gantt. Use `proposed_slots` for per-step machine and time ranges.

### Load existing schedule

1. Call `GET /jobs` to list jobs.
2. For each job (or on demand): `GET /ai/scheduling/jobs/{job_id}/proposals`.
3. Use latest draft proposal’s `proposed_slots` to render the schedule.

### Display structure

| Field                 | Use for                        |
|-----------------------|--------------------------------|
| `job_id`              | Group slots by job             |
| `earliest_start`      | Job start time                 |
| `estimated_completion`| Job end time                   |
| `deadline_status`     | Mark late jobs; show `late_by` badge |
| `proposed_slots`      | Each step: machine, start, end |
| `proposal_id`         | Apply / approve / verify       |

---

## Example: JavaScript/React

```javascript
const BASE = 'http://localhost:8080/api/v1';
const headers = { 'Content-Type': 'application/json', 'X-User-Role': 'planner' };

// Generate schedule (use 30s+ timeout for batch-proposals)
const controller = new AbortController();
const timeoutId = setTimeout(() => controller.abort(), 60000); // 60s
const batch = await fetch(`${BASE}/ai/scheduling/batch-proposals`, {
  method: 'POST',
  headers,
  body: JSON.stringify({ scope: 'all_unscheduled' }),
  signal: controller.signal,
}).then(r => r.json());
clearTimeout(timeoutId);

// Check for partial results on timeout
if (batch.data?.partial) {
  console.warn(batch.data.message); // partial results returned
}

const proposals = batch.data.proposals;
const proposalIds = proposals.map(p => p.proposal_id);

// Verify
const verify = await fetch(`${BASE}/ai/scheduling/verify-overlaps`, {
  method: 'POST',
  headers,
  body: JSON.stringify({ proposal_ids: proposalIds }),
}).then(r => r.json());

// Display
if (verify.data.valid) {
  // Render proposals and proposed_slots (e.g. table or Gantt)
  proposals.forEach(p => {
    console.log(p.job_id, p.earliest_start, p.estimated_completion);
    p.proposed_slots.forEach(slot => {
      console.log(`  ${slot.machine_name}: ${slot.scheduled_start} - ${slot.scheduled_end}`);
    });
  });
} else {
  console.warn('Overlaps:', verify.data.overlaps);
}
```
