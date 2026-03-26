# Chatbot Query Examples (Frontend Reference)

**Endpoint:** `POST /api/v1/ai/command`  
**Body:** `{ "query": "<user input>", "execute_readonly": true }`

Run `go run ./cmd/seed` to load seed data, then use the IDs below for testing.

---

## Seed IDs (use these after seeding)

| Type | IDs |
|------|-----|
| **Jobs** | `JOB-SEED-001` … `JOB-SEED-012` |
| **Job steps** | `JS-SEED-001-1`, `JS-SEED-001-2`, … (per job) |
| **Proposals** | `AIPROP-SEED-001` (draft for JOB-SEED-001) |
| **Products** | `P-001` … `P-009` |
| **Machines** | `M-CNC-01`, `M-LTH-01`, `M-CTG-01`, `M-ASM-01`, `M-QC-01`, etc. |
| **Materials** | `MAT-001`, `MAT-005`, `MAT-008`, etc. |

---

## Schedule & Proposals

| Query | Intent | Seed test |
|-------|--------|-----------|
| Propose a schedule for job JOB-SEED-001 | propose_schedule | ✅ |
| Suggest a schedule for JOB-SEED-002 | propose_schedule | ✅ |
| Recommend a plan for JOB-SEED-007 | propose_schedule | ✅ |
| Schedule all jobs | schedule_all_jobs | ✅ |
| Assign all jobs | schedule_all_jobs | ✅ |
| Optimize schedule for all | schedule_all_jobs | ✅ |
| Apply proposal AIPROP-SEED-001 | apply_proposal | ✅ (approve first) |
| Approve proposal AIPROP-SEED-001 | approve_proposal | ✅ |
| Reject proposal AIPROP-SEED-001 | reject_proposal | ✅ |

---

## Jobs

| Query | Intent | Seed test |
|-------|--------|-----------|
| Create job for P-001 100 units | create_job | ✅ |
| Add job for 50 units of P-002 deadline Mar 15, 2026 | create_job | ✅ |
| Reschedule job JOB-SEED-001 | reschedule_job | ✅ |
| Move slot for JOB-SEED-002 to tomorrow | reschedule_job | ✅ |
| Cancel job JOB-SEED-001 | cancel_job | ✅ |
| Delete job JOB-SEED-012 | cancel_job | ✅ |
| Status of job JOB-SEED-001 | query_status | ✅ |
| Explain job JOB-SEED-001 | explain_job | ✅ |
| Why is job JOB-SEED-003 delayed? | explain_job | ✅ |
| Delay risk for job JOB-SEED-006 | delay_risk | ✅ |

---

## Machines & Material

| Query | Intent | Seed test |
|-------|--------|-----------|
| Rank machines for job step JS-SEED-001-1 | machine_ranking | ✅ |
| Best machine for step JS-SEED-002-1 | machine_ranking | ✅ |
| Consume 50 kg of MAT-001 for job JOB-SEED-001 | consume_material | ✅ |
| Deduct 10 units of MAT-005 | consume_material | ✅ |

---

## Reports & Status

| Query | Intent |
|-------|--------|
| Job status | query_status |
| List jobs | query_status |
| Production report | report_request |
| OEE report | report_request |
| Bottleneck forecast | report_request |

---

## Quick test flow

1. **Reseed:** `go run ./cmd/seed`
2. **Propose schedule (executed):**  
   `POST /ai/command` with `{"query": "propose schedule for JOB-SEED-001", "execute_readonly": true}`
3. **Get new proposal:** `GET /ai/scheduling/jobs/JOB-SEED-001/proposals` → pick `proposal_id`
4. **Approve:** `POST /ai/scheduling/proposals/<id>/approve`
5. **Apply:** `POST /ai/scheduling/proposals/<id>/apply`
6. **Delete job:** `DELETE /jobs/JOB-SEED-012` (use `job_id`, not `product_id`)

---

## Tips

- Use **job_id** (e.g. `JOB-SEED-001`) for job operations—`product_id` (e.g. `P-001`) is different.
- Set `execute_readonly: true` to auto-run propose, explain, delay-risk, machine-ranking, status.
- Write intents (approve, reject, apply, schedule_all_jobs, reschedule, cancel, consume) return `suggested_calls`; frontend should call those APIs after confirmation.
- For `schedule_all_jobs`, suggested call: `POST /ai/scheduling/batch-proposals` with body `{"scope":"all_unscheduled"}`.
