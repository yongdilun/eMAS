# AI Chat Bot: Test Messages and Expected Frontend Behavior

Use these messages to test the chat bot. Each section lists test inputs and the expected frontend behavior.

---

## Approval Rule (Reference)

| HTTP Method | Requires Approval | Frontend Behavior |
|-------------|-------------------|-------------------|
| **GET** | No | Auto-execute; show result in card/chip |
| **POST/PUT/DELETE** | Yes | Show action card with **Approve** button; execute only after user clicks |

---

## 1. Propose Schedule (GET + POST; GET no approval, POST approval)

**Test messages:**
- "Suggest schedule for job JOB-SEED-001"
- "Propose a schedule for JOB-SEED-002"
- "Recommend a plan for job JOB-SEED-003, don't apply yet"

**Expected behavior:**
- Assistant returns message + `suggested_calls` with:
  - **GET** `/api/v1/ai/scheduling/jobs/JOB-SEED-001/assist` → `requires_approval: false` → **Auto-run**; show assist/insights in card
  - **POST** `/api/v1/ai/scheduling/jobs/JOB-SEED-001/proposals` → `requires_approval: true` → Show **Approve** button; on click, call API, show success/error

---

## 2. Explain Job (GET; no approval)

**Test messages:**
- "Explain job JOB-SEED-001"
- "What's going on with JOB-SEED-002?"
- "Why is job JOB-SEED-003 delayed?"

**Expected behavior:**
- `suggested_calls` with **GET** `/api/v1/ai/scheduling/jobs/{id}/explanation` → `requires_approval: false`
- **Auto-execute** GET; show explanation in card. No Approve button.

---

## 3. Delay Risk (GET; no approval)

**Test messages:**
- "What's the delay risk for job JOB-SEED-001?"
- "Will JOB-SEED-002 miss the deadline?"
- "Is JOB-SEED-003 at risk? Don't move it."

**Expected behavior:**
- `suggested_calls` with **GET** `/api/v1/ai/scheduling/jobs/{id}/delay-risk` → `requires_approval: false`
- **Auto-execute** GET; show risk score/assessment in card. No Approve button.

---

## 4. Machine Ranking (GET; no approval)

**Test messages:**
- "Rank machines for job step JS-SEED-001-1"
- "Which machine is best for JS-SEED-001-2?"
- "Best machine for step JS-SEED-002-1"

**Expected behavior:**
- `suggested_calls` with **GET** `/api/v1/ai/scheduling/job-steps/{id}/machine-ranking` → `requires_approval: false`
- **Auto-execute** GET; show machine ranking in card. No Approve button.

---

## 5. Approve Proposal (POST; approval required)

**Test messages:**
- "Approve proposal AIPROP-SEED-001"
- "Looks good, approve AIPROP-SEED-001"
- "OK approve that proposal"

**Expected behavior:**
- `suggested_calls` with **POST** `/api/v1/ai/scheduling/proposals/{id}/approve` → `requires_approval: true`
- Show action card with **Approve** button. User must click to execute. Show success/error toast.

---

## 6. Reject Proposal (POST; approval required)

**Test messages:**
- "Reject proposal AIPROP-SEED-001"
- "Decline proposal AIPROP-SEED-001"
- "Don't approve, reject it"

**Expected behavior:**
- `suggested_calls` with **POST** `/api/v1/ai/scheduling/proposals/{id}/reject` → `requires_approval: true`
- Show action card with **Approve** button. User must click to execute.

---

## 7. Apply Proposal (POST; approval required)

**Test messages:**
- "Apply proposal for job JOB-SEED-001"
- "Apply proposal AIPROP-SEED-001"
- "Write the schedule to the job plan"

**Expected behavior:**
- `suggested_calls` with **POST** apply → `requires_approval: true`
- Show action card with **Approve** button. User must click to execute. On error (e.g. "slot is outside resource work calendar"), show toast with backend message.

---

## 8. Schedule All Jobs (POST; approval required)

**Test messages:**
- "Schedule all unscheduled jobs"
- "Batch schedule all jobs"
- "Auto-schedule everything"

**Expected behavior:**
- `suggested_calls` with **POST** `/api/v1/ai/scheduling/batch-proposals` → `requires_approval: true`
- Show action card with **Approve** button. User must click to execute.

---

## 9. Create Job (POST; approval required)

**Test messages:**
- "Create a job for 100 units of P-001"
- "Add 50 units of Valve Body Assembly"
- "New job: 20x P-002"

**Expected behavior:**
- `suggested_calls` with **POST** `/api/v1/jobs` and body `{ product_id, quantity_total }` → `requires_approval: true`
- Show action card with **Approve** button. User must click to execute.
- If `ambiguous: true` (e.g. missing quantity), show clarifications; do not show Approve until user provides missing info.

---

## 10. Cancel Job (DELETE; approval required)

**Test messages:**
- "Cancel job JOB-SEED-001"
- "Remove JOB-SEED-002 from the plan"
- "Delete job JOB-SEED-003"

**Expected behavior:**
- `suggested_calls` with **DELETE** `/api/v1/jobs/{id}` → `requires_approval: true`
- Show action card with **Approve** button. User must click to execute.

---

## 11. Reschedule Job (GET + POST; GET no approval, POST approval)

**Test messages:**
- "Reschedule job JOB-SEED-001 to later today"
- "Move JOB-SEED-002 to tomorrow morning"
- "Push JOB-SEED-003 to next week"

**Expected behavior:**
- `suggested_calls` with GET assist + POST proposals → GET auto-run, POST needs **Approve**.

---

## 12. Query Status (GET; no approval)

**Test messages:**
- "Show status of job JOB-SEED-001"
- "List machines status"
- "What's the inventory status?"
- "Quick status snapshot"
- "List all jobs"

**Expected behavior:**
- `suggested_calls` with **GET** (jobs, machines, inventory, dashboard/kpis, alerts) → `requires_approval: false`
- **Auto-execute** GET; show result in card. No Approve button.

---

## 13. Consume Material (POST; approval required)

**Test messages:**
- "Consume 10 kg of MAT-001 for job JOB-SEED-001"
- "Use 5 units of steel"

**Expected behavior:**
- `suggested_calls` with **POST** `/api/v1/inventory/consume` → `requires_approval: true`
- Show action card with **Approve** button.

---

## 14. Receive Material (POST; approval required)

**Test messages:**
- "Receive 100 units of MAT-001"
- "Record incoming material MAT-005, 50 kg"

**Expected behavior:**
- `suggested_calls` with **POST** `/api/v1/inventory/receive` → `requires_approval: true`
- Show action card with **Approve** button.

---

## 15. Record Downtime (POST; approval required)

**Test messages:**
- "Record downtime for machine M-CNC-01"
- "M-LTH-01 is down, log it"
- "Machine M-CTG-01 offline for maintenance"

**Expected behavior:**
- `suggested_calls` with **POST** `/api/v1/machines/downtime` → `requires_approval: true`
- Show action card with **Approve** button.

---

## 16. Maintenance Alerts (GET; no approval)

**Test messages:**
- "Show maintenance alerts"
- "Which machines need maintenance?"

**Expected behavior:**
- `suggested_calls` with **GET** `/api/v1/machines/maintenance-alerts` → `requires_approval: false`
- **Auto-execute** GET; show alerts in card.

---

## 17. List Products (GET; no approval)

**Test messages:**
- "List all products"
- "Show products"

**Expected behavior:**
- `suggested_calls` with **GET** `/api/v1/products` → `requires_approval: false`
- **Auto-execute** GET; show product list in card.

---

## 18. High-Risk Jobs (GET; no approval)

**Test messages:**
- "Which jobs are at high risk?"
- "Show high-risk jobs forecast"

**Expected behavior:**
- `suggested_calls` with **GET** `/api/v1/predictive/high-risk-jobs` → `requires_approval: false`
- **Auto-execute** GET; show forecast in card.

---

## 19. Dashboard KPIs (GET; no approval)

**Test messages:**
- "Show dashboard KPIs"
- "What are the key metrics?"

**Expected behavior:**
- `suggested_calls` with **GET** `/api/v1/dashboard/kpis` → `requires_approval: false`
- **Auto-execute** GET; show KPIs in card.

---

## 20. Generate Report (GET; no approval)

**Test messages:**
- "Generate utilization report"
- "Give me an OEE report"
- "Bottleneck forecast"
- "Production output report"

**Expected behavior:**
- `suggested_calls` with **GET** reports (utilization, OEE, bottleneck, etc.) → `requires_approval: false`
- **Auto-execute** GET; show report in card.

---

## 21. Split Step (GET; no approval)

**Test messages:**
- "Split suggestion for job step JS-SEED-001-1"
- "Can we split step JS-SEED-001-2 across machines?"

**Expected behavior:**
- `suggested_calls` with **GET** `/api/v1/ai/scheduling/job-steps/{id}/split-suggestion` → `requires_approval: false`
- **Auto-execute** GET; show split suggestion in card.

---

## 22. Unknown / Ambiguous (no API, show clarification)

**Test messages:**
- "Just wondering about the plan"
- "Hey can you look at stuff"
- "Approve this please" (no proposal ID)

**Expected behavior:**
- `intent: "unknown"` or `ambiguous: true`
- Show clarifications; no `suggested_calls` or calls with missing entities
- Do **not** show Approve. Ask user to specify job/proposal ID or intent.

---

## Seed IDs for Testing

| Type | Example IDs |
|------|-------------|
| Jobs | JOB-SEED-001 … JOB-SEED-018 |
| Job steps | JS-SEED-001-1, JS-SEED-001-2, … |
| Proposals | AIPROP-SEED-001 |
| Products | P-001 … P-009 (e.g. P-001 = Valve Body Assembly) |
| Machines | M-CNC-01, M-LTH-01, M-CTG-01, … |
| Materials | MAT-001, MAT-005, MAT-008, … |

---

## Quick Test Matrix

| Intent | Sample Message | Approve? |
|--------|----------------|----------|
| propose_schedule | "Propose schedule for JOB-SEED-001" | GET: No; POST: Yes |
| explain_job | "Explain job JOB-SEED-001" | No |
| delay_risk | "Delay risk for JOB-SEED-001?" | No |
| machine_ranking | "Rank machines for JS-SEED-001-1" | No |
| approve_proposal | "Approve AIPROP-SEED-001" | Yes |
| reject_proposal | "Reject AIPROP-SEED-001" | Yes |
| apply_proposal | "Apply proposal for JOB-SEED-001" | Yes |
| schedule_all_jobs | "Schedule all jobs" | Yes |
| create_job | "Create job 100 units of P-001" | Yes |
| cancel_job | "Cancel JOB-SEED-001" | Yes |
| reschedule | "Reschedule JOB-SEED-001 to tomorrow" | GET: No; POST: Yes |
| query_status | "Status of machines" | No |
| consume_material | "Consume 10 of MAT-001" | Yes |
| receive_material | "Receive 50 of MAT-001" | Yes |
| record_downtime | "Downtime for M-CNC-01" | Yes |
| maintenance_alerts | "Maintenance alerts" | No |
| list_products | "List products" | No |
| high_risk_jobs | "High-risk jobs" | No |
| dashboard_kpis | "Dashboard KPIs" | No |
| generate_report | "Utilization report" | No |
| split_step | "Split suggestion for JS-SEED-001-1" | No |
