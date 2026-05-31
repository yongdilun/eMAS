# Reschedule-All System Audit

Date: 2026-05-31

Scope: Go backend scheduling, reschedule-all, proposal apply, inventory reservation, production progress, and auto-reschedule paths.

## Executive Summary

The current `reschedule-all` flow is not strong enough for a live manufacturing system that already has scheduled work and partial execution. It is a synchronous cancel-and-regenerate path. It has some inventory-aware planning logic, but the surrounding lifecycle does not preserve progress, does not release stale reservations, does not atomically swap schedules, and does not have a persistent progress/run model.

The two biggest gaps are:

1. `RescheduleAll` cancels existing slots and deletes proposals before the replacement schedule is guaranteed. If generation fails or times out, the system can be left with cancelled slots and no replacement.
2. Production progress exists in the data model, but the planner does not consume it. Reschedule builds proposals from full `quantity_total` and full step `quantity_target`, so a partially completed job can be scheduled from the beginning again.

Confidence: high. The findings below are based on direct call-chain tracing and a focused service test run:

```text
go test ./internal/service -run "RescheduleAll|ProductionLog|AllocateProposalReservations" -count=1
ok emas/internal/service
```

## Files Inspected

- `internal/handler/ai_scheduling_handler.go`
- `internal/handler/dto/dto.go`
- `internal/service/multi_job_scheduler.go`
- `internal/service/ai_scheduling_service.go`
- `internal/service/ai_proposal_support.go`
- `internal/service/proposal_apply_inventory.go`
- `internal/service/production_log_service.go`
- `internal/service/scheduling_preview_service.go`
- `internal/service/scheduling_service.go`
- `internal/service/scheduling_support.go`
- `internal/service/subproduct_planner.go`
- `internal/service/job_slot_service.go`
- `internal/repository/job_slot_repo.go`
- `internal/repository/inventory_repo.go`
- `internal/repository/ai_proposal_repo.go`
- `internal/repository/scheduling_event_repo.go`
- `internal/domain/job.go`
- `internal/domain/job_slot.go`
- `internal/domain/inventory.go`
- `internal/domain/product_inventory_reservation.go`
- `internal/domain/production_log.go`
- `internal/domain/wip_inventory.go`
- `internal/domain/scheduling_event.go`
- `pkg/featureflags/flags.go`

## Current Flow

1. `POST /ai/scheduling/reschedule-all` binds `RescheduleAllRequest` and calls `h.service.RescheduleAll(...)`.
   Evidence: `internal/handler/ai_scheduling_handler.go:176-186`.

2. The request only supports `order_by` and `dry_run`; there is no scope, run id, idempotency key, progress mode, preserve-progress flag, or conflict policy.
   Evidence: `internal/handler/dto/dto.go:449-453`.

3. `RescheduleAll` resolves planned/scheduled jobs, cancels planned/running slots, deletes proposals, then calls `ScheduleJobSet`.
   Evidence: `internal/service/multi_job_scheduler.go:28-58`.

4. `ScheduleJobSet` creates an in-memory planning batch, excludes existing reservations for selected job IDs during planning, builds proposals, persists drafts, and later returns proposals plus a summary.
   Evidence: `internal/service/multi_job_scheduler.go:139-178`, `internal/service/multi_job_scheduler.go:219-390`, `internal/service/multi_job_scheduler.go:531-544`.

5. Applying a proposal creates inventory/product reservations and new slots inside a transaction, then marks the proposal applied.
   Evidence: `internal/service/ai_proposal_support.go:1363-1627`, `internal/service/proposal_apply_inventory.go:16-107`.

6. Production logs update slot, step, job status, WIP, reservations, and proposal outcome.
   Evidence: `internal/service/production_log_service.go:52-158`, `internal/service/production_log_service.go:161-248`.

## Findings

### F1. Reschedule-all is not atomic and can leave the system unscheduled

Severity: Critical

`RescheduleAll` mutates the live schedule before the new schedule is known to be valid. It loops through jobs, cancels existing planned/running slots, deletes proposals, and only then calls `ScheduleJobSet`.

Evidence:

- Existing slots are cancelled before regeneration: `internal/service/multi_job_scheduler.go:37-46`.
- Existing proposals are deleted before regeneration: `internal/service/multi_job_scheduler.go:47-50`.
- Replacement schedule generation happens after those mutations: `internal/service/multi_job_scheduler.go:53-58`.
- `ScheduleJobSet` can return partial results on context timeout/cancel: `internal/service/multi_job_scheduler.go:144-146`, `internal/service/multi_job_scheduler.go:220-222`.
- The handler returns partial results if timeout happens after some proposals: `internal/handler/ai_scheduling_handler.go:188-197`.

Why this matters:

If proposal generation errors, times out, or panics after old slots are cancelled, the current operational schedule is already damaged. Because cancellation is not wrapped together with draft generation and replacement activation, there is no rollback boundary.

Required direction:

- Introduce a two-phase reschedule:
  - Phase 1: build replacement plan in a run-owned staging area.
  - Phase 2: atomically swap old future slots/reservations to cancelled/released and activate new slots/reservations.
- Do not cancel live schedule rows until all replacement proposals have passed validation.
- Keep a schedule snapshot before swap for rollback/audit.

### F2. Slot/proposal update errors are ignored during reschedule cancellation

Severity: Critical

Inside `RescheduleAll`, repository errors are ignored while listing slots, updating slots, and deleting proposals.

Evidence:

- `slots, _ := s.slotRepo.ListByJobID(jobID)`: `internal/service/multi_job_scheduler.go:39`.
- `_ = s.slotRepo.Update(&slot)`: `internal/service/multi_job_scheduler.go:43`.
- `_ = s.proposalRepo.DeleteByJobID(jobID)`: `internal/service/multi_job_scheduler.go:49`.

Why this matters:

The API can report success even if some slots failed to cancel or some proposals failed to delete. That can create mixed old/new schedules, hidden overlaps, duplicate proposal histories, and stale apply targets.

Required direction:

- Return and fail on every mutation error.
- Execute cancellation/deletion in one DB transaction.
- Log run item errors with exact job ID, slot ID, proposal ID, and failed operation.

### F3. There is no global reschedule lock or run-level concurrency guard

Severity: Critical

The system has row locks for inventory material consume/receive, but no lock around `reschedule-all`, proposal generation, proposal apply, or auto-reschedule.

Evidence:

- Inventory has `GetMaterialByIDForUpdate`, but only for material rows: `internal/repository/inventory_repo.go:29-39`.
- `RescheduleAll` has no transaction or mutex/advisory lock: `internal/service/multi_job_scheduler.go:28-58`.
- `NextVersion` reads latest proposal version without locking: `internal/repository/ai_proposal_repo.go:52-62`.
- Apply runs in a transaction, but it only rejects if non-cancelled slots already exist for that job; it does not protect the whole scheduler from a concurrent reschedule: `internal/service/ai_proposal_support.go:1366-1392`.
- Auto-reschedule starts a full reschedule from event handling without a lock and swallows the result: `internal/service/ai_scheduling_service.go:1501-1504`.

Why this matters:

Two planners, or one planner and one auto-reschedule event, can run at the same time. They can both cancel, generate, delete, stale, and apply against moving state.

Required direction:

- Add a scheduler operation lock, preferably DB-backed:
  - MySQL advisory lock such as `GET_LOCK('scheduler:reschedule-all', timeout)` or a `scheduler_locks` table.
  - Include owner, token, expires_at, heartbeat_at.
- Make proposal apply acquire a compatible per-job/per-schedule lock.
- Add request idempotency for `reschedule-all`, not just proposal apply.

### F4. Lock-in window is a filter/floor, not a robust lock policy

Severity: High

The lock-in window skips jobs when their earliest active slot starts within the configured window and sets an earliest start floor for regenerated proposals. This is useful, but incomplete.

Evidence:

- Job eligibility uses only planned/scheduled jobs and earliest active start: `internal/service/multi_job_scheduler.go:61-87`.
- The earliest active query only considers planned/running slots and only the earliest `scheduled_start`: `internal/repository/job_slot_repo.go:166-188`.
- Regenerated proposals are floored to `now + lock window`: `internal/service/multi_job_scheduler.go:90-99`.
- The existing test only verifies an imminent planned slot is skipped: `internal/service/multi_job_scheduler_test.go:11-91`.

Gaps:

- It does not lock by job/slot state with a persisted reason.
- It does not preserve already completed steps/slots as immutable history for a replan.
- It does not model in-progress quantities.
- It does not prevent another process from updating slots while reschedule is running.
- It does not handle the case where the job status is still `scheduled` but some steps are already completed and future slots start outside the window.

Required direction:

- Split lock policy into:
  - hard immutable execution history: completed slots/logs/WIP/consumed reservations,
  - active execution lock: running/paused slots and their downstream constraints,
  - soft planning floor: do not schedule new work before `lockUntil`.
- Store lock decisions per run item so the UI can explain why each job was skipped, preserved, or partially replanned.

### F5. Reschedule ignores production progress and schedules full quantities again

Severity: Critical

The domain has progress fields, but scheduling does not use them as remaining work.

Evidence:

- Job has `quantity_total` and `quantity_completed`: `internal/domain/job.go:30-43`.
- Job step has `quantity_target` and `quantity_completed`: `internal/domain/job.go:56-65`.
- Slot has `quantity_planned`, `actual_start`, and `actual_end`: `internal/domain/job_slot.go:14-35`.
- Production logs increment step and job completed quantities: `internal/service/production_log_service.go:110-132`.
- Build preview checks readiness for full `job.QuantityTotal`: `internal/service/scheduling_preview_service.go:67`.
- Preview stores full `job.QuantityTotal`: `internal/service/scheduling_preview_service.go:92-99`.
- Each preview step uses full `jobStep.QuantityTarget`: `internal/service/scheduling_preview_service.go:126-180`.
- Proposal slot quantities allocate full `step.QuantityTarget`: `internal/service/ai_proposal_support.go:563-605`.
- `QuantityCompleted` is only visible in a high-risk score, not in actual scheduling quantity: `internal/service/ai_scheduling_service.go:1007-1010`.

Why this matters:

If a 100-unit job has completed 40 units, reschedule still plans the full step target unless the old future slots happen to remain locked out. This matches the user's concern that reschedule "starts over without any progress."

Required direction:

- Add a canonical remaining-work calculation:
  - `job_remaining_qty = max(quantity_total - quantity_completed, 0)`
  - `step_remaining_qty = max(quantity_target - quantity_completed, 0)`
  - `slot_remaining_qty = max(quantity_planned - produced_for_slot - scrap_policy_qty, 0)`
- Make preview, BOM explosion, duration estimation, split allocation, and reservation generation use remaining quantities.
- Treat completed steps as fixed predecessors, not new schedulable work.
- Treat partially completed current step as a reduced continuation slot, not a full restart.

### F6. Old reservations are not released when old slots are cancelled

Severity: Critical

Reschedule cancels slots and deletes proposals, but it does not release material reservations, product reservations, or planned product inventory rows created by the old applied proposal.

Evidence:

- `RescheduleAll` only cancels slots and deletes proposals: `internal/service/multi_job_scheduler.go:37-50`.
- Material reservations are keyed to job/step, not proposal/slot: `internal/domain/inventory.go:102-115`.
- Product reservations are keyed to job/step, not proposal/slot: `internal/domain/product_inventory_reservation.go:5-17`.
- Product planned inventory rows are created at apply time: `internal/service/proposal_apply_inventory.go:40-53`.
- Product inventory has no proposal ID, slot ID, or source run ID field: `internal/domain/inventory.go:81-93`.
- There is a `released` reservation status, but no release path is used by reschedule: `internal/domain/inventory.go:95-100`; search found no release service.
- `ScheduleJobSet` explicitly excludes selected job IDs' existing reservations during planning: `internal/service/multi_job_scheduler.go:171-178`.
- Apply does not exclude/release old reservations before creating new ones: `internal/service/proposal_apply_inventory.go:55-104`.

Why this matters:

Planning can ignore old reservations and look feasible, but apply can still see the old pending reservations in the DB and either fail or double reserve. Also, old planned product inventory can remain visible as future stock even after the old schedule is cancelled.

Required direction:

- Add `proposal_id`, `slot_id`, or `schedule_run_id` to reservations and planned product inventory.
- On reschedule swap, release old pending reservations and planned product inventory rows for cancelled future work.
- Keep consumed reservations immutable.
- Add tests where a rescheduled job has old pending reservations and the new apply does not double count them.

### F7. Production execution consumes reservation rows but not the stock ledgers

Severity: Critical

Production logging marks reservations as consumed or reduces reservation row quantities, but it does not decrement material `current_stock` or product inventory `quantity_on_hand`.

Evidence:

- Material reservation consumption only updates reservation rows: `internal/service/production_log_service.go:282-310`.
- Product reservation consumption only updates product reservation rows: `internal/service/production_log_service.go:313-337`.
- Material stock decrement exists in `InventoryService.ConsumeMaterial`, but that is a separate endpoint/service path: `internal/service/inventory_service.go:21-50`.
- Product availability reads `quantity_on_hand - quantity_reserved` and pending reservation rows: `internal/service/scheduling_support.go:819-875`.

Why this matters:

After production consumes material or product stock, future scheduling can overestimate available stock because the underlying stock row still contains consumed quantity once the reservation row is no longer pending. This weakens inventory-aware rescheduling.

Required direction:

- When a production log consumes reserved material, also decrement material `current_stock` and create an inventory transaction.
- When a production log consumes product inventory, decrement the specific product inventory lot/row or create a consumption transaction table.
- Link reservations to source inventory rows/lots if FIFO or exact allocation matters.
- Add invariant tests:
  - pending reservation reduces availability,
  - consumed reservation also reduces physical stock,
  - released reservation restores availability,
  - consumed reservation never restores availability.

### F8. Planned product inventory can be double counted after actual production

Severity: High

Apply creates `planned` product inventory to represent future dependent production. Production logs later create new `available` product inventory output, but there is no transition from planned to available and no cleanup of the planned row.

Evidence:

- Planned inventory is intentionally created during apply: `internal/domain/inventory.go:74-78`, `internal/service/proposal_apply_inventory.go:40-53`.
- Actual production output creates a separate available product inventory row: `internal/service/production_log_service.go:229-240`.
- Product inventory rows do not have source proposal/slot/run fields to reconcile planned vs actual: `internal/domain/inventory.go:81-93`.

Why this matters:

The planner may see both the old planned stock and the actual available stock as supply, especially after child/dependent production completes. This can make future reschedule results look feasible when they are not.

Required direction:

- Treat planned product inventory as a commitment, not a stock lot.
- Add source references and transition states:
  - planned -> available when output is logged,
  - planned -> cancelled/released when its source slot is cancelled,
  - planned -> adjusted when actual output differs from plan.

### F9. No persistent progress system exists for reschedule-all itself

Severity: High

`reschedule-all` is synchronous and returns only proposals plus a summary. There is no durable run table, run item table, progress endpoint, resumable state, or operation journal.

Evidence:

- Request DTO has only `order_by` and `dry_run`: `internal/handler/dto/dto.go:449-453`.
- Handler returns immediate `proposals` and `summary`: `internal/handler/ai_scheduling_handler.go:210-217`.
- Summary is aggregate counters only: `internal/service/multi_job_scheduler.go:1045-1060`.
- Scheduling events contain only ID/type/payload/created_at, no processing status or link to a reschedule run: `internal/domain/scheduling_event.go:12-20`.

Why this matters:

Large reschedules need job-level progress, idempotency, resume, cancellation, and precise failure reporting. Without this, users cannot know whether a partial run is safe to continue, retry, or roll back.

Required direction:

Add:

- `reschedule_runs`
  - `run_id`, `status`, `requested_by`, `scope_hash`, `order_by`, `dry_run`, `lock_until`, `started_at`, `finished_at`, `error`, `idempotency_key`.
- `reschedule_run_items`
  - `run_id`, `job_id`, `status`, `phase`, `old_slot_ids`, `new_proposal_id`, `preserved_progress_qty`, `remaining_qty`, `error`.
- APIs:
  - `POST /ai/scheduling/reschedule-all` starts or resumes a run.
  - `GET /ai/scheduling/reschedule-runs/:id` returns progress.
  - `POST /ai/scheduling/reschedule-runs/:id/apply` performs atomic swap.

### F10. Auto-reschedule setting path is inconsistent and errors are swallowed

Severity: Medium

The settings handler stores `scheduling.auto_reschedule_on_event`, but the runtime auto-reschedule trigger reads `AI_AUTO_RESCHEDULE_ON_EVENT` from environment feature flags. Also, auto-triggered `RescheduleAll` ignores errors.

Evidence:

- DB setting constants and update path: `internal/handler/scheduling_settings_handler.go:21-37`, `internal/handler/scheduling_settings_handler.go:267-272`.
- Runtime flag reads environment variable: `pkg/featureflags/flags.go:144-147`.
- Event trigger ignores return values: `internal/service/ai_scheduling_service.go:1501-1504`.

Why this matters:

The UI/user can believe auto-reschedule is enabled while the backend event path still uses the environment flag. If an event-triggered reschedule fails, no durable failure is recorded.

Required direction:

- Use one source of truth for auto-reschedule.
- Event-triggered reschedules should enqueue a `reschedule_run`, not run synchronously in the event call.
- Store failure status on the event/run.

### F11. Handler accepts invalid JSON silently for reschedule-all

Severity: Low

`RescheduleAll` ignores `ShouldBindJSON` errors.

Evidence:

- `_ = c.ShouldBindJSON(&req)`: `internal/handler/ai_scheduling_handler.go:177-178`.

Why this matters:

Malformed JSON falls through as an empty request. This is not the main scheduling risk, but it makes client bugs harder to detect.

Required direction:

- Return `400 invalid request body` on JSON bind errors, matching `GenerateBatchProposals`.

## Recommended Architecture

### A. Make Reschedule a Run, Not a Direct Mutation

State model:

```text
queued -> planning -> validating -> ready_to_apply -> applying -> applied
                         |              |
                         v              v
                       failed        cancelled
```

Per-job item phases:

```text
pending -> inspected -> preserved_progress -> proposal_generated -> validated -> swapped
```

Key rules:

- A run never cancels live slots during `planning`.
- The run records old active slots, completed slots, reservations, WIP, and production logs.
- The run computes remaining quantities before scheduling.
- Apply swaps future mutable state in one transaction.
- Completed execution state is never deleted or rewritten.

### B. Add a Scheduler Lock

Minimum viable lock:

- `scheduler_locks(name primary key, owner, token, expires_at, heartbeat_at)`
- Lock names:
  - `scheduler:reschedule-all`
  - `scheduler:job:<job_id>`
  - `scheduler:proposal-apply:<job_id>`

Rules:

- `reschedule-all` acquires the global lock.
- proposal apply acquires the job lock.
- auto-reschedule enqueues if lock is busy.
- stale lock recovery requires token/expiry checks.

### C. Add Remaining-Work Calculation

Create one service helper used by preview, BOM, duration, reservations, and apply:

```text
remaining_step_qty =
  quantity_target
  - sum(production_logs.quantity_produced for completed/running slots of step)
  - accepted_good_wip_for_step_if_applicable
```

Then:

- Do not generate slots for `remaining_step_qty == 0`.
- Use `remaining_step_qty` for material demand.
- Use `remaining_step_qty` for duration estimation.
- Use `remaining_step_qty` for split allocation.
- Preserve completed slots and production logs as immutable history.

### D. Fix Inventory Lifecycle

Add explicit reservation lifecycle methods:

- `ReserveMaterial`
- `ReleaseMaterialReservation`
- `ConsumeMaterialReservation`
- `ReserveProduct`
- `ReleaseProductReservation`
- `ConsumeProductReservation`
- `CancelPlannedProductOutput`
- `RealizePlannedProductOutput`

Each method should update both reservation/commitment rows and physical stock rows inside one transaction.

### E. Add Tests Before Implementation

Suggested tests:

1. `TestRescheduleAll_DoesNotMutateLiveScheduleWhenPlanningFails`
2. `TestRescheduleAll_ReleasesOldPendingReservationsOnApplySwap`
3. `TestRescheduleAll_PreservesCompletedSlotsAndSchedulesOnlyRemainingQty`
4. `TestRescheduleAll_RunningSlotInsideLockWindowIsPreserved`
5. `TestProductionLog_ConsumesMaterialReservationAndCurrentStock`
6. `TestProductionLog_ConsumesProductReservationAndProductStock`
7. `TestPlannedProductInventory_IsRealizedOrCancelled`
8. `TestConcurrentRescheduleAll_SecondRunRejectedOrQueued`
9. `TestAutoReschedule_UsesDBSettingAndCreatesRunFailure`

## Suggested Implementation Order

1. Add audit-safe tests for the critical failures.
2. Add run tables and scheduler lock.
3. Refactor `RescheduleAll` into plan-only plus atomic apply/swap.
4. Add remaining-work calculation and wire it into preview/proposal/BOM/reservation generation.
5. Add reservation release/consume/realize lifecycle methods.
6. Move auto-reschedule to enqueue a run and expose run progress.
7. Fix handler JSON validation and expand response metadata.

## Bottom Line

The existing system has useful pieces: lock-in window, inventory-aware planning ledgers, reservations, production logs, WIP, and transactional proposal apply. The gap is that these pieces are not connected into one reliable reschedule lifecycle.

To make reschedule-all safe, the system needs a persistent run/progress model, a real scheduler lock, atomic schedule swap, remaining-quantity scheduling, and an inventory lifecycle that releases old commitments and consumes physical stock correctly.
