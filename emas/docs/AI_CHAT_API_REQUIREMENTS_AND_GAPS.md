# AI Chat — API Requirements and Gaps for Expected Behavior

**Purpose:** Before implementing [AI_CHAT_TEST_MESSAGES_AND_FRONTEND_BEHAVIOR.md](./AI_CHAT_TEST_MESSAGES_AND_FRONTEND_BEHAVIOR.md), ensure backend and frontend can meet expected behavior. This document lists required API contracts, response shapes, and gaps.

---

## 1. Backend AI Response Contract

### Source of suggested_calls

The frontend expects `suggested_calls` from either:

- **POST /api/v1/ai/chats/:id/messages** — when chats are implemented (returns 200)
- **POST /api/v1/ai/command** — fallback when chats return 404 (stateless)

**Required:** At least one of these must return `suggested_calls` for the frontend to show action cards.

### suggested_call structure

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `method` | string | Yes | `GET`, `POST`, `PUT`, `PATCH`, `DELETE` |
| `path` | string | Yes | e.g. `/jobs/JOB-SEED-001` or `/api/v1/jobs/JOB-SEED-001` — frontend normalizes |
| `body` | object \| null | For POST/PUT/PATCH | Request body; null for GET/DELETE |
| `purpose` | string | No | Human-readable description for UI |
| `requires_approval` | boolean | Yes | `false` for GET (auto-run); `true` for POST/PUT/PATCH/DELETE |

### Top-level response fields (for message display)

| Field | Type | Purpose |
|-------|------|---------|
| `message` | string | Assistant reply text |
| `intent` | string | Parsed intent (e.g. `propose_schedule`, `cancel_job`) |
| `ambiguous` | boolean | If true, show clarifications; do not show Approve |
| `clarifications` | string[] | Follow-up prompts when info is missing |
| `result_cards` | array | Pre-built UI cards (see below) |
| `entities` | object | e.g. `{ job_id, proposal_id, product_id }` |

---

## 2. Auto-Execute vs Approve

| HTTP Method | requires_approval | Expected frontend behavior |
|-------------|-------------------|----------------------------|
| GET | false | **Auto-execute**; call API, show result in card. No Approve button. |
| POST/PUT/PATCH/DELETE | true | Show **Approve** button; execute only on click. |

**Gap:** Current frontend shows "Run" for GET (user must click). To meet expected behavior, frontend should **auto-execute** GET suggested_calls when `requires_approval: false` and display the response in a result card.

---

## 3. API Endpoints — Request Bodies (Backend must populate `body` in suggested_calls)

### POST /jobs (create_job)

**Path:** `/jobs` or `/api/v1/jobs`  
**Body (from entities):**

```json
{
  "product_id": "P-001",
  "quantity_total": 100,
  "priority": "optional",
  "deadline": "optional RFC3339",
  "notes": "optional"
}
```

- `product_id` — Product ID (e.g. P-001, P-002). From "Create job 100 units of P-001".
- `quantity_total` — Integer. From "100 units".

**Ambiguous:** If user says "Create a job for Valve Body Assembly" without quantity, return `ambiguous: true`, `clarifications: ["How many units?"]`. Do not include suggested_calls for create until resolved.

---

### POST /inventory/consume (consume_material)

**Path:** `/inventory/consume` or `/api/v1/inventory/consume`  
**Body:**

```json
{
  "material_id": "MAT-001",
  "quantity": 10,
  "reference_job_id": "JOB-SEED-001",
  "slot_id": "optional"
}
```

- `material_id` — From "Consume 10 kg of MAT-001".
- `quantity` — Numeric. Parse from message (e.g. 10, 50).
- `reference_job_id` — If user says "for job JOB-SEED-001".

---

### POST /inventory/receive (receive_material)

**Path:** `/inventory/receive` or `/api/v1/inventory/receive`  
**Body:**

```json
{
  "material_id": "MAT-001",
  "quantity": 100
}
```

---

### POST /machines/downtime (record_downtime)

**Path:** `/machines/downtime` or `/api/v1/machines/downtime`  
**Body:**

```json
{
  "machine_id": "M-CNC-01",
  "cause": "Maintenance",
  "start_time": "optional RFC3339",
  "end_time": "optional RFC3339"
}
```

- `machine_id` — From "Record downtime for machine M-CNC-01".

---

### POST /ai/scheduling/batch-proposals (schedule_all_jobs)

**Path:** `/ai/scheduling/batch-proposals`  
**Body:**

```json
{
  "scope": "all_unscheduled",
  "order_by": "optional"
}
```

---

### POST /ai/scheduling/proposals/:id/approve

**Path:** `/ai/scheduling/proposals/AIPROP-SEED-001/approve`  
**Body:** `{}` or null

---

### POST /ai/scheduling/proposals/:id/reject

**Path:** `/ai/scheduling/proposals/AIPROP-SEED-001/reject`  
**Body:** `{}` or null

---

### POST /ai/scheduling/proposals/:id/apply

**Path:** `/ai/scheduling/proposals/AIPROP-SEED-001/apply`  
**Body:** `{}` or null

- **Apply by job:** If user says "Apply proposal for job JOB-SEED-001", backend must resolve to a proposal_id and return path `/ai/scheduling/proposals/{proposal_id}/apply`.

---

### DELETE /jobs/:id (cancel_job)

**Path:** `/jobs/JOB-SEED-001`  
**Body:** null

---

## 4. GET Endpoints — Response Shapes (for result card display)

When the frontend auto-executes a GET suggested_call, it needs to render the response. These shapes are for reference.

### GET /ai/scheduling/jobs/:id/assist

```json
{
  "data": {
    "job_id": "JOB-SEED-001",
    "readiness": {},
    "solver_preview": {},
    "delay_risk": { "risk_level": "High", "risk_score": 0.8 },
    "explanation": ["..."]
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

### GET /ai/scheduling/job-steps/:id/machine-ranking

**Path:** `/ai/scheduling/job-steps/JS-SEED-001-1/machine-ranking`  
**Query:** `?start=...&end=...` (optional)

```json
{
  "data": {
    "job_step_id": "JS-SEED-001-1",
    "rankings": [{ "machine_id": "...", "score": 0.9, "reason": "..." }]
  }
}
```

### GET /ai/scheduling/job-steps/:id/split-suggestion

```json
{
  "data": {
    "job_step_id": "JS-SEED-001-1",
    "suggestions": [...]
  }
}
```

### GET /jobs, /machines, /products (query_status)

- **GET /jobs** — `{ data: Job[] }`
- **GET /machines** — `{ data: Machine[] }`
- **GET /products** — `{ data: Product[] }`

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

### GET /alerts

```json
{
  "data": [{ "type": "maintenance", "message": "...", "severity": "..." }]
}
```

### GET /machines/maintenance-alerts

```json
{
  "data": [{ "machine_id": "...", "machine_name": "...", "due_date": "..." }]
}
```

### GET /predictive/high-risk-jobs

```json
{
  "data": [{ "job_id": "...", "risk_level": "...", "product_name": "..." }]
}
```

### GET /reports/* (generate_report)

| User says | Path |
|-----------|------|
| "Utilization report" | `/reports/machine-utilization` |
| "OEE report" | `/reports/oee` |
| "Bottleneck forecast" | `/reports/bottlenecks` or `/ai/scheduling/bottleneck-forecast?days_ahead=5` |
| "Production output report" | `/reports/production-output` |

---

## 5. result_cards Structure (Pre-built by backend)

When the backend executes a read-only action internally (e.g. via `execute_readonly: true`), it can return `result_cards` instead of relying on frontend to call suggested_calls. Each card:

```json
{
  "kind": "delay_risk",
  "title": "Delay Risk for JOB-SEED-001",
  "tone": "warning",
  "summary": "High risk: 120 min late",
  "metrics": [
    { "label": "Risk", "value": "High" },
    { "label": "Score", "value": "0.8" }
  ],
  "bullets": ["Reason 1", "Reason 2"]
}
```

**tone:** `positive` | `info` | `warning` | `critical`  
**kind:** `delay_risk`, `job_explanation`, `machine_ranking`, `schedule_proposal`, `job_status`, etc.

---

## 6. Error Handling

### Apply proposal — work calendar error

When apply fails with "slot is outside resource work calendar", backend returns 400/422 with message. Frontend must show the error in a toast (already in `apiErrorMessage`).

### Ambiguous create_job

- Backend returns `ambiguous: true`, `clarifications: ["How many units?", "Which product?"]`.
- Frontend must **not** show Approve until user provides missing info and backend returns a non-ambiguous response with suggested_calls.

---

## 7. Path Format

The frontend `executeSuggestedCall` accepts:

- `/jobs/JOB-SEED-001` — prepends `BASE_URL` (http://localhost:8080/api/v1)
- `/api/v1/jobs/JOB-SEED-001` — strips `/api/v1` and prepends BASE_URL (same result)

Backend can send either. Path must not include origin (no `http://localhost:8080`).

---

## 8. Summary — Gaps Fulfilled

| Area | Status |
|------|--------|
| **Backend** | ✅ Implemented. `suggested_calls` with `body` populated for create_job, consume, receive, downtime. |
| **Frontend** | See [AI_CHAT_FRONTEND_NEEDS.md](./AI_CHAT_FRONTEND_NEEDS.md): Add **auto-execute** for GET when `requires_approval: false`. |
| **Apply by job** | ✅ Backend resolves job_id → proposal_id; returns path `/ai/scheduling/proposals/{id}/apply`. |
| **Ambiguous** | ✅ When create_job/consume/receive missing entities, backend returns `ambiguous: true` and no `suggested_calls`. |

---

## 9. Seed IDs Reference

| Type | Example |
|------|---------|
| Jobs | JOB-SEED-001 … JOB-SEED-018 |
| Job steps | JS-SEED-001-1, JS-SEED-001-2 |
| Proposals | AIPROP-SEED-001 |
| Products | P-001 … P-009 |
| Machines | M-CNC-01, M-LTH-01, M-CTG-01 |
| Materials | MAT-001, MAT-005, MAT-008 |
