# AI Chat: Frontend Action Display and Approval Guide

This document explains how the frontend should display actions from the AI chat and when user approval is required before executing API calls.

---

## Approval Rule

| HTTP Method | Requires Approval | Frontend Behavior |
|-------------|-------------------|-------------------|
| **GET**     | No                | Execute immediately; display result |
| **POST**    | Yes               | Show action with "Approve" button; execute only when user confirms |
| **PUT**     | Yes               | Show action with "Approve" button; execute only when user confirms |
| **PATCH**   | Yes               | Show action with "Approve" button; execute only when user confirms |
| **DELETE**  | Yes               | Show action with "Approve" button; execute only when user confirms |

**Rule:** Any action that **changes data** (create, update, delete) must wait for user approval. Read-only (GET) actions can be called directly.

---

## Response Structure

From `POST /api/v1/ai/command` or `POST /api/v1/ai/chats/:id/messages`:

```json
{
  "intent": "cancel_job",
  "action": "cancel_job",
  "entities": { "job_id": "JOB-SEED-001" },
  "suggested_calls": [
    {
      "method": "DELETE",
      "path": "/api/v1/jobs/JOB-SEED-001",
      "body": null,
      "purpose": "Cancel the job.",
      "requires_approval": true
    }
  ],
  "execution_mode": "blocked_write_action",
  "bdi_result": { ... }
}
```

Each `suggested_call` has:
- `method` – HTTP method
- `path` – Full API path (prefixed with `/api/v1` or base URL)
- `body` – Request body for POST/PUT/PATCH (null for GET/DELETE)
- `purpose` – Human-readable description
- `requires_approval` – `true` if user must confirm before calling

---

## How to Display Actions

### 1. For GET (requires_approval: false)

- **Option A:** Call the API in the background and show the result in a card.
- **Option B:** Show a clickable action card; when user clicks, call the API and display the result.

No confirmation dialog is needed.

### 2. For POST/PUT/PATCH/DELETE (requires_approval: true)

1. Show an action card with:
   - Method badge (e.g. POST, DELETE)
   - Purpose text
   - Summary of what will change (e.g. "Cancel job JOB-SEED-001")
2. Add an **"Approve"** or **"Execute"** button.
3. When user clicks Approve:
   - Call the API: `method` + `path` + `body` (if any)
   - Show success/error feedback
   - Refresh affected data if needed

### 3. Execution Modes

| execution_mode          | Meaning |
|-------------------------|---------|
| `suggest_only`          | Parsed only; no API called yet |
| `executed_readonly`     | A GET was auto-executed; result in `insights` |
| `blocked_write_action`  | Write action detected; show suggested_calls and wait for approval |
| `readonly_execution_failed` | GET failed; check `guidance` |

---

## Full Intent and Action Reference

Every intent, its suggested calls, and whether approval is required.

| Intent | Description | Suggested Calls | Requires Approval |
|--------|-------------|-----------------|-------------------|
| **propose_schedule** | Propose schedule for a job | GET assist, POST proposals | GET: No; POST: Yes |
| **approve_proposal** | Approve a persisted proposal | POST approve | Yes |
| **reject_proposal** | Reject a proposal | POST reject | Yes |
| **apply_proposal** | Apply proposal to job | POST apply or POST proposals | Yes |
| **schedule_all_jobs** | Batch schedule unscheduled jobs | POST batch-proposals | Yes |
| **explain_job** | Explain job status | GET explanation | No |
| **delay_risk** | Delay risk for job | GET delay-risk | No |
| **machine_ranking** | Rank machines for job step | GET machine-ranking | No |
| **create_job** | Create a new job | POST /jobs | Yes |
| **reschedule** | Reschedule a job | GET assist, POST proposals | GET: No; POST: Yes |
| **cancel_job** | Cancel a job | DELETE /jobs/:id | Yes |
| **query_status** | Status of jobs/machines/inventory | GET jobs, machines, materials, kpis, alerts | No |
| **consume_material** | Consume material from inventory | POST /inventory/consume | Yes |
| **receive_material** | Receive material into inventory | POST /inventory/receive | Yes |
| **record_downtime** | Record machine downtime | POST /machines/downtime | Yes |
| **maintenance_alerts** | Maintenance alerts | GET maintenance-alerts | No |
| **list_products** | List products | GET /products | No |
| **high_risk_jobs** | High-risk jobs forecast | GET high-risk-jobs | No |
| **dashboard_kpis** | Dashboard KPIs | GET /dashboard/kpis | No |
| **generate_report** | Various reports | GET reports/* | No |
| **split_step** | Split suggestion for job step | GET split-suggestion | No |

---

## Example: Call Execution Logic

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

  if (call.requires_approval) {
    const confirmed = await showConfirmDialog(
      `Execute: ${call.purpose}\n${call.method} ${call.path}`
    );
    if (!confirmed) return;
  }

  const res = await fetch(url, options);
  // Handle response, show success/error, refresh UI
}
```

---

## UI Pattern Summary

| requires_approval | Display |
|-------------------|---------|
| `false` | Action chip/card; click to run (or auto-run for read-only) |
| `true`  | Action card with "Approve" button; run only after click |

---

## Seed IDs for Testing

| Type | Example IDs |
|------|-------------|
| Jobs | JOB-SEED-001 … JOB-SEED-018 |
| Job steps | JS-SEED-001-1, JS-SEED-002-1, … |
| Proposals | AIPROP-SEED-001 |
| Products | P-001 … P-009 |
| Machines | M-CNC-01, M-LTH-01, M-CTG-01, … |
| Materials | MAT-001, MAT-005, MAT-008, … |
