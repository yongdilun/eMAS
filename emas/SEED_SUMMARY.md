# Seed Data Summary

**Run:** `go run ./cmd/seed`

**Schedule:** All jobs compacted to one week — **2026-01-06 (Mon) to 2026-01-12 (Sun)**. Deadlines and slot times within this window.

---

## Entities

| Entity | Count | IDs |
|--------|-------|-----|
| **Products** | 9 | P-001 … P-009 |
| **Machines** | 8 | M-CNC-01, M-CNC-02, M-LTH-01, M-LTH-02, M-PRS-01, M-CTG-01, M-ASM-01, M-QC-01 |
| **Processes** | 9 | PRC-001 … PRC-009 (one per product) |
| **Formulas** | 9 | F-001 … F-009 |
| **Materials** | 14 | MAT-001 … MAT-014 |
| **Jobs** | 12 | JOB-SEED-001 … JOB-SEED-012 |
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
| JOB-SEED-001 … JOB-SEED-012 | (various) | (various) | planned | (various) | **no** (all unscheduled) |

**All jobs are unscheduled.** Schedule via `POST /ai/scheduling/batch-proposals` with `{"scope":"all_unscheduled"}`.

**Job steps:** `JS-SEED-{n}-{step}` (e.g. JS-SEED-001-1)  
**Slots:** `SLOT-SEED-{n}-{slot}` (e.g. SLOT-SEED-001-1)

---

## Other

- **Product inventory:** 3 items (P-007, P-008, P-009)
- **Inventory reservations:** 3 (MAT-005→JOB-SEED-001, MAT-007→JOB-SEED-002, MAT-012→JOB-SEED-003)
- **Expected arrivals:** 3 (MAT-007, MAT-002, MAT-005)
- **Maintenance records:** 3
- **Downtime records:** 2
- **Production logs:** ~5
- **Quality inspections:** ~3
