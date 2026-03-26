# Scheduler Deep Analysis

## Executive Summary

The current heuristic scheduler produces **feasible, non-overlapping** schedules but exhibits **scattered timelines** and **non-compact** placement. Jobs spread across multiple weeks (Mar 9, Mar 16, Mar 23) instead of packing into a tight window. Root causes: material readiness delays, greedy machine selection, and no makespan/compactness objective.

---

## 1. Observed Schedule Behavior

### Timeline (from batch run)

| Job        | Priority | Earliest start | Est. completion | Span |
|------------|----------|----------------|-----------------|------|
| JOB-SEED-001 | high   | Mar 9  19:32  | Mar 10 01:47  | ~6h |
| JOB-SEED-003 | high   | **Mar 16** 19:07 | Mar 16 22:47 | ~4h |
| JOB-SEED-006 | high   | **Mar 16** 20:17 | Mar 16 23:32 | ~3h |
| JOB-SEED-008 | high   | Mar 9  19:32  | Mar 9  23:17  | ~4h |
| JOB-SEED-011 | high   | Mar 9  19:32  | Mar 9  23:42  | ~4h |
| JOB-SEED-002 | medium | Mar 9  19:32  | Mar 10 02:32  | ~7h |
| JOB-SEED-004 | medium | Mar 9  19:59  | Mar 10 02:57  | ~7h |
| JOB-SEED-007 | medium | **Mar 23** 23:17 | Mar 24 05:32 | ~6h |
| JOB-SEED-010 | medium | Mar 9  19:49  | Mar 10 04:27  | ~9h |
| JOB-SEED-005 | low    | Mar 9  19:32  | Mar 9  20:24  | ~1h |
| JOB-SEED-009 | low    | **Mar 16** 19:07 | Mar 17 01:17 | ~6h |
| JOB-SEED-012 | low    | Mar 9  19:32  | Mar 9  19:46  | ~15m |

### Why It Looks Random

1. **Scattered start dates**: Jobs start on Mar 9, Mar 16, and Mar 23 — not in a contiguous block.
2. **Priority vs. timeline mismatch**: High-priority 003 starts Mar 16; medium 002 starts Mar 9.
3. **Same-day starts**: Many jobs share ~19:32 on Mar 9 but differ by seconds, creating a noisy timeline.
4. **Large gaps**: Week-long gaps between clusters.

---

## 2. Root Causes

### 2.1 Material Readiness (EarliestReadyAt)

The preview uses `CheckReadiness(productID, quantity)` and sets `cursor = EarliestReadyAt` when materials or sub-products are not ready. This pushes jobs into the future.

**Seed data drivers:**
- **Expected arrivals**: MAT-007, MAT-002, MAT-005 have future arrival times.
- **Sub-product BOM**: P-001 (Valve Body) needs P-007 and P-008. P-006 (Pump Casing) needs P-003, P-009.
- **Product inventory**: P-008 has `AvailableFrom: now + 12h`; others use `now`.

**Effect:** Jobs depending on P-003, P-006, P-007, P-008, P-009, or late-arriving materials get `EarliestReadyAt` far in the future (e.g. Mar 16, Mar 23), so they cannot start earlier even if machines are free.

### 2.2 Job Ordering (EPO)

Order: priority (high → medium → low), then deadline. All seed jobs share the same deadline, so within a priority tier the order is effectively by array index, not by readiness or duration.

**Effect:** A high-priority job with late readiness (e.g. 003) is still processed early in the batch, but its start time is already pushed to Mar 16. No reordering to pack jobs that *can* start now.

### 2.3 Greedy Machine Selection

For each step, the heuristic:
1. Filters candidates with `Available` or `AvailableFrom` within the window.
2. Sorts by: `Available` (true first) → `EfficiencyFactor` (higher first) → `CapacityPerHour` (higher first).
3. Picks the **first** candidate and schedules the step at `max(cursor, AvailableFrom)`.

**What it does not do:**
- No look-ahead for later jobs.
- No objective to minimize makespan, idle time, or changeovers.
- No evaluation of alternative machines for compactness.
- No backfilling of gaps.

**Effect:** Feasible and deterministic, but not optimized for utilization or compactness.

### 2.4 Sequential Batch Processing

Jobs are processed in EPO order. Each job’s tentative slots are added to `tentativeSlots` for the next job. This correctly avoids machine overlaps but does not:
- Reorder jobs by readiness.
- Interleave jobs to fill gaps.
- Consider global objectives.

### 2.5 Single Global Cursor

Each job starts with `cursor = time.Now()` or `EarliestReadyAt`. There is no shared “global clock” or planning horizon that drives jobs to start as early as possible as a whole.

---

## 3. Why the Schedule Is Not Compact

| Cause | Impact |
|-------|--------|
| Readiness pushes jobs weeks out | Jobs 003, 006, 007, 009 start Mar 16–23 instead of Mar 9. |
| No readiness-aware reordering | Late-ready high-priority jobs block a compact layout. |
| Greedy machine choice | First-feasible machine, not best for makespan. |
| No makespan objective | Scheduler does not minimize total schedule length. |
| No gap filling | Idle machine time is not used to pull other jobs forward. |

---

## 4. Current Scheduler Rating

| Dimension | Score (1–5) | Notes |
|-----------|-------------|-------|
| **Feasibility** | 5/5 | No overlaps, respects precedence and machine capability. |
| **Correctness** | 5/5 | Tentative slots, duration-aware `NextFreeWindow` work correctly. |
| **Compactness** | 1/5 | Jobs spread over ~2 weeks; large gaps. |
| **Makespan** | 2/5 | Long total span; not optimized. |
| **Utilization** | 2/5 | Gaps and readiness-driven delays leave machines idle. |
| **Deadline awareness** | 2/5 | EPO uses deadlines for tie-break only; no explicit tardiness handling. |
| **Transparency** | 4/5 | Clear reasoning and candidate ranking. |
| **Speed** | 5/5 | Fast, no optimization search. |

### Overall: **3/5** — Good feasibility engine, weak optimization

---

## 4b. Re-evaluation After Reschedule-All + Phases 1–3

**API:** `POST /api/v1/ai/scheduling/reschedule-all` with `{"order_by":"readiness"}`  
**Flow:** 1) Cancel all active slots for planned/scheduled jobs; 2) Delete proposals; 3) Regenerate via ScheduleJobSet (same as batch-proposals).

**Improvements (Phases 1–3):**
- **Readiness-aware ordering** (order_by=readiness): Jobs that can start sooner are scheduled first.
- **Earliest-finish machine selection**: Each step picks the machine that yields the earliest completion time.
- **Reschedule-all** provides a clean slate for re-optimization.

**Expected rating change:**

| Dimension      | Before | After (estimate) |
|----------------|--------|------------------|
| Feasibility    | 5/5    | 5/5              |
| Correctness    | 5/5    | 5/5              |
| Compactness    | 1/5    | 2–3/5            |
| Makespan       | 2/5    | 2–3/5            |
| Utilization    | 2/5    | 2–3/5            |
| Transparency   | 4/5    | 4/5              |
| Speed          | 5/5    | 5/5              |

**How to evaluate:** Run `scripts/evaluate_reschedule.ps1` after restarting the server. Then call verify-overlaps on the returned proposal_ids and inspect the timeline in `reschedule_output.json`.

---

## 5. Recommendations

### Short term (low effort)
1. **Readiness-aware ordering**: When using EPO, sort by `EarliestReadyAt` within each priority tier so jobs that can start sooner are scheduled first.
2. **Shared planning anchor**: Use `max(now, min(EarliestReadyAt across jobs))` or a configurable horizon so more jobs can start in the same window when possible.

### Medium term
3. **Makespan objective**: Add a secondary sort or scoring that favors machines/slots that reduce total schedule length.
4. **Gap-aware placement**: Before placing a step, check for gaps on machines and prefer slots that fill gaps over extending the schedule.

### Long term
5. **Real solver / MIP**: Use the existing solver path or a MIP/CP formulation to minimize makespan or tardiness.
6. **Two-phase scheduling**: Phase 1: resolve readiness and estimate windows; Phase 2: optimize placement with a compactness objective.
