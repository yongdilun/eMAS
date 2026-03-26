# AI Chat — Frontend Integration Guide

**Purpose:** Single source of truth for frontend integration with the AI Chat API. All backend gaps from `AI_CHAT_API_REQUIREMENTS_AND_GAPS.md` are fulfilled.

---

## 1. Endpoints

| Endpoint | Use when |
|----------|----------|
| `POST /api/v1/ai/command` | Stateless parsing; no conversation context |
| `POST /api/v1/ai/chats/:id/messages` | Chat UI; persists messages, returns same response shape |

Both return the same response structure. Prefer chats when the user is in a conversation flow.

---

## 2. Response Structure

```json
{
  "success": true,
  "data": {
    "intent": "cancel_job",
    "action": "cancel_job",
    "entities": { "job_id": "JOB-SEED-001" },
    "message": "I'll cancel job JOB-SEED-001.",
    "ambiguous": false,
    "clarifications": [],
    "suggested_calls": [
      {
        "method": "DELETE",
        "path": "/api/v1/jobs/JOB-SEED-001",
        "body": null,
        "purpose": "Cancel the job.",
        "requires_approval": true
      }
    ],
    "result_cards": [],
    "execution_mode": "blocked_write_action"
  }
}
```

### Top-level fields (for display)

| Field | Type | Purpose |
|-------|------|---------|
| `message` | string | Assistant reply text — show in chat bubble |
| `intent` | string | Parsed intent (e.g. `propose_schedule`, `cancel_job`) |
| `ambiguous` | boolean | If true, show `clarifications`; do **not** show Approve |
| `clarifications` | string[] | Follow-up prompts when info is missing |
| `suggested_calls` | array | API calls to execute (see below) |
| `result_cards` | array | Pre-built UI cards (optional; use when present) |
| `entities` | object | Extracted entities (e.g. `job_id`, `proposal_id`) |

---

## 3. suggested_call Structure

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `method` | string | Yes | `GET`, `POST`, `PUT`, `PATCH`, `DELETE` |
| `path` | string | Yes | e.g. `/api/v1/jobs/JOB-SEED-001` (no origin) |
| `body` | object \| null | For POST/PUT/PATCH | Request body; null for GET/DELETE |
| `purpose` | string | No | Human-readable description |
| `requires_approval` | boolean | Yes | `false` = auto-execute; `true` = show Approve button |

### Path format

- Backend sends paths like `/api/v1/jobs/JOB-SEED-001` (no origin).
- Frontend prepends `BASE_URL` (e.g. `http://localhost:8080`) when calling.
- Paths without `/api/v1` prefix are also valid; normalize as needed.

---

## 4. Approval Rule (Critical)

| HTTP Method | `requires_approval` | Frontend behavior |
|-------------|---------------------|-------------------|
| **GET** | `false` | **Auto-execute**; call API, show result in card. No Approve button. |
| **POST / PUT / PATCH / DELETE** | `true` | Show **Approve** button; execute only when user clicks. |

**When `ambiguous: true`:** Show `clarifications` to the user. Do **not** show Approve or suggested_calls until the user provides the missing info and the backend returns a non-ambiguous response.

---

## 5. How to Execute suggested_calls

### GET (requires_approval: false)

- **Option A (recommended):** Auto-execute in the background when the message arrives; display the result in a card.
- **Option B:** Show a clickable chip; when user clicks, call API and display result.

### POST / PUT / PATCH / DELETE (requires_approval: true)

1. Show action card with method badge, purpose, and summary.
2. Add **Approve** (or **Execute**) button.
3. On click: call `method` + `path` + `body`; show success/error toast; refresh UI as needed.

### Example execution logic

```javascript
async function executeAction(call) {
  const url = `${API_BASE}${call.path}`;
  const options = {
    method: call.method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (call.body && ['POST', 'PUT', 'PATCH'].includes(call.method)) {
    options.body = JSON.stringify(call.body);
  }
  const res = await fetch(url, options);
  // Handle response, show success/error, refresh UI
}
```

---

## 6. Intent → suggested_calls Reference

| Intent | Suggested Calls | GET auto? | POST/PUT/DELETE approve? |
|--------|-----------------|-----------|---------------------------|
| `propose_schedule` | GET assist, POST proposals | GET: yes | POST: yes |
| `explain_job` | GET explanation, GET delay-risk | yes | — |
| `delay_risk` | GET delay-risk | yes | — |
| `machine_ranking` | GET machine-ranking | yes | — |
| `approve_proposal` | GET proposal, POST approve | GET: yes | POST: yes |
| `reject_proposal` | GET proposal, POST reject | GET: yes | POST: yes |
| `apply_proposal` | GET proposal, POST approve, POST apply | GET: yes | POST: yes |
| `schedule_all_jobs` | POST batch-proposals | — | yes |
| `create_job` | POST /jobs | — | yes |
| `reschedule` | GET assist, POST proposals | GET: yes | POST: yes |
| `cancel_job` | DELETE /jobs/:id | — | yes |
| `query_status` | GET jobs/machines/kpis/alerts | yes | — |
| `consume_material` | POST /inventory/consume | — | yes |
| `receive_material` | POST /inventory/receive | — | yes |
| `record_downtime` | POST /machines/downtime | — | yes |
| `maintenance_alerts` | GET maintenance-alerts | yes | — |
| `list_products` | GET /products | yes | — |
| `high_risk_jobs` | GET high-risk-jobs | yes | — |
| `dashboard_kpis` | GET /dashboard/kpis | yes | — |
| `generate_report` | GET reports/* | yes | — |
| `split_step` | GET split-suggestion | yes | — |

---

## 7. API Request Bodies (Backend Populates `body` in suggested_calls)

### POST /jobs (create_job)

```json
{
  "product_id": "P-001",
  "quantity_total": 100,
  "priority": "optional",
  "deadline": "optional RFC3339",
  "notes": "optional"
}
```

### POST /inventory/consume (consume_material)

```json
{
  "material_id": "MAT-001",
  "quantity": 10,
  "reference_job_id": "JOB-SEED-001",
  "slot_id": "optional"
}
```

### POST /inventory/receive (receive_material)

```json
{
  "material_id": "MAT-001",
  "quantity": 100
}
```

### POST /machines/downtime (record_downtime)

```json
{
  "machine_id": "M-CNC-01",
  "cause": "Maintenance",
  "start_time": "optional RFC3339",
  "end_time": "optional RFC3339"
}
```

### POST /ai/scheduling/batch-proposals (schedule_all_jobs)

```json
{
  "scope": "all_unscheduled",
  "order_by": "optional"
}
```

### POST /ai/scheduling/proposals/:id/approve | reject | apply

Body: `{}` or null.

---

## 8. Apply Proposal by Job

When the user says **"Apply proposal for job JOB-SEED-001"**, the backend resolves `job_id` → `proposal_id` and returns:

- `POST /api/v1/ai/scheduling/proposals/{proposal_id}/approve`
- `POST /api/v1/ai/scheduling/proposals/{proposal_id}/apply`

If no proposal exists for the job, the backend returns generate/list/preview suggested_calls instead.

---

## 9. GET Endpoint Response Shapes (for result card display)

When you auto-execute a GET suggested_call, you receive `{ success, data }`. The `data` shape varies by endpoint. Examples:

### GET /ai/scheduling/jobs/:id/delay-risk

```json
{
  "data": {
    "job_id": "JOB-SEED-001",
    "risk_level": "High",
    "risk_score": 0.8,
    "issue": "...",
    "delay_minutes": 120,
    "reasons": ["..."]
  }
}
```

### GET /ai/scheduling/jobs/:id/explanation

```json
{
  "data": {
    "job_id": "JOB-SEED-001",
    "summary": "...",
    "key_points": ["..."],
    "recommended_actions": ["..."]
  }
}
```

### GET /dashboard/kpis

```json
{
  "data": {
    "oee_pct": 85.2,
    "production_units": 24180,
    "downtime_hrs": 2.1,
    "utilization_pct": 78
  }
}
```

### GET /jobs, /machines, /products

```json
{ "data": [ /* array of items */ ] }
```

---

## 10. result_cards Structure

When the backend includes `result_cards`, each card has:

| Field | Type | Notes |
|-------|------|-------|
| `kind` | string | `delay_risk`, `job_explanation`, `machine_ranking`, `schedule_proposal`, `job_status`, etc. |
| `title` | string | Card header |
| `tone` | string | `positive` \| `info` \| `warning` \| `critical` |
| `summary` | string | Short description |
| `metrics` | array | `[{ "label": "...", "value": "..." }]` |
| `bullets` | string[] | Additional points |
| `actions` | array | Optional `suggested_calls` nested in the card |

---

## 11. Error Handling

**Authoritative batch apply contract:** [`SCHEDULING_APPLY_ALL_INTEGRATION_CONTRACT.md`](./SCHEDULING_APPLY_ALL_INTEGRATION_CONTRACT.md).  
Use that document as the single source for apply-all sequencing, stale handling, overlap verification scope, and retry behavior.

### Apply proposal — work calendar error

When apply fails with "slot is outside resource work calendar", the API returns 400/422 with detail like:

`slot is outside resource work calendar (job_step_id=..., machine_id=..., start=..., end=...). Refresh work calendars and regenerate proposals before apply`

Frontend behavior:

1. Show **one** toast with the backend message.
2. If applying many proposals, **stop the batch on first work-calendar error** (do not continue and spam repeated errors).
3. Prompt user to run:
   - `POST /api/v1/scheduling/refresh-work-calendars`
   - regenerate proposals (`POST /api/v1/ai/scheduling/batch-proposals` or per-job proposals)
   - then apply again.

### Apply proposal — stale error during Apply All

If frontend applies many proposals sequentially, proposal 2+ can become stale after proposal 1 changes DB state.

Required frontend request body for Apply All:

```json
{
  "skip_staleness_check": true,
  "idempotency_key": "apply-all-<batch-id>-<proposal-id>"
}
```

Use this body for both:

- `POST /api/v1/ai/scheduling/proposals/:id/approve`
- `POST /api/v1/ai/scheduling/proposals/:id/apply`

If frontend does **not** send `skip_staleness_check: true`, backend will return 409 stale by design.

### Ambiguous create_job / consume / receive

- Backend returns `ambiguous: true`, `clarifications: ["How many units?", "Which product?"]`.
- **Do not** show Approve. Show clarifications; wait for user to provide info; send a follow-up message.

---

## 12. Seed IDs for Testing

| Type | Examples |
|------|----------|
| Jobs | JOB-SEED-001 … JOB-SEED-018 |
| Job steps | JS-SEED-001-1, JS-SEED-001-2 |
| Proposals | AIPROP-SEED-001 |
| Products | P-001 … P-009 |
| Machines | M-CNC-01, M-LTH-01, M-CTG-01 |
| Materials | MAT-001, MAT-005, MAT-008 |

---

## 13. Test Messages (from AI_CHAT_TEST_MESSAGES_AND_FRONTEND_BEHAVIOR.md)

Use these to verify behavior:

- **Propose:** "Suggest schedule for job JOB-SEED-001"
- **Explain:** "Explain job JOB-SEED-001"
- **Delay risk:** "What's the delay risk for job JOB-SEED-001?"
- **Machine ranking:** "Rank machines for job step JS-SEED-001-1"
- **Approve:** "Approve proposal AIPROP-SEED-001"
- **Apply:** "Apply proposal for job JOB-SEED-001"
- **Create job:** "Create job 100 units of P-001"
- **Cancel:** "Cancel job JOB-SEED-001"
- **Consume:** "Consume 10 kg of MAT-001 for job JOB-SEED-001"
- **Receive:** "Receive 100 kg of MAT-001"
- **Downtime:** "Record downtime for machine M-CNC-01"
- **Status:** "Show job status", "List machines", "Dashboard KPIs"

---

## 14. Checklist for Frontend

- [ ] Call `POST /api/v1/ai/command` or `POST /api/v1/ai/chats/:id/messages` with user query
- [ ] Display `message` in chat bubble
- [ ] When `ambiguous: true`, show `clarifications`; do **not** show Approve
- [ ] When `suggested_calls` has GET with `requires_approval: false`, **auto-execute** and show result in card
- [ ] When `suggested_calls` has POST/PUT/DELETE with `requires_approval: true`, show Approve button; execute on click
- [ ] Prepend `BASE_URL` to `path` when calling APIs
- [ ] Handle apply work-calendar errors with toast
- [ ] Use seed IDs for manual testing
