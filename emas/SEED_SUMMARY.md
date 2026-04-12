# Seed Data Summary

**Run:** `go run ./cmd/seed`

**Schedule:** Seed jobs are unscheduled by default. Generate proposals with `POST /ai/scheduling/batch-proposals`.

---

## Entities

| Entity | Count | IDs |
|--------|-------|-----|
| **Products** | 9 | P-001 ... P-009 |
| **Machines** | 8 | M-CNC-01, M-CNC-02, M-LTH-01, M-LTH-02, M-PRS-01, M-CTG-01, M-ASM-01, M-QC-01 |
| **Processes** | 9 | PRC-001 ... PRC-009 (one per product) |
| **Formulas** | 9 | F-001 ... F-009 |
| **Materials** | 14 | MAT-001 ... MAT-014 |
| **Jobs** | 18 | JOB-SEED-001 ... JOB-SEED-018 |
| **AI proposals** | 0 | (created by batch-proposals API) |

---

## Products

| ID | Name |
|----|------|
| P-001 | Valve Body Assembly |
| P-002 | Precision Gear Set |
| P-003 | Hydraulic Cylinder Rod |
| P-004 | Motor Housing |
| P-005 | Control Bracket |
| P-006 | Pump Casing |
| P-007 | Seal Kit |
| P-008 | Valve Spool Assembly |
| P-009 | Pump Gasket Set |

---

## Jobs

| job_id | product_id | qty | status | priority | slots |
|--------|------------|-----|--------|----------|-------|
| JOB-SEED-001 ... JOB-SEED-018 | mixed | 120 ... 520 | planned | high/medium/low | **no** (all unscheduled) |

**All jobs are unscheduled.** Schedule via `POST /ai/scheduling/batch-proposals` with `{"scope":"all_unscheduled"}`.

**Job steps:** `JS-SEED-{n}-{step}` (example: `JS-SEED-001-1`)
**Slots:** `SLOT-SEED-{n}-{slot}` (example: `SLOT-SEED-001-1`)

---

## Other

- **Product inventory:** 4 items (`P-003`, `P-007`, `P-008`, `P-009`)
- **Inventory reservations:** 3 (`MAT-005 -> JOB-SEED-001`, `MAT-007 -> JOB-SEED-002`, `MAT-012 -> JOB-SEED-003`)
- **Expected arrivals:** 3 (`MAT-007`, `MAT-002`, `MAT-005`)
- **Maintenance records:** 3
- **Downtime records:** 2
- **Production logs:** about 5
- **Quality inspections:** about 3
