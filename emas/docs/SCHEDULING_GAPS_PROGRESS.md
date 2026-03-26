# Scheduling Gaps Progress

**API changelog:** [`SCHEDULING_GAPS_API_CHANGELOG.md`](SCHEDULING_GAPS_API_CHANGELOG.md) – API changes and additions.  
**Frontend improvements:** [`SCHEDULING_GAPS_FRONTEND_IMPROVEMENTS.md`](SCHEDULING_GAPS_FRONTEND_IMPROVEMENTS.md) – UI/UX changes to support gaps.

| # | Gap | Phase | Status | Updated | Notes |
|---|-----|-------|--------|---------|-------|
| 1 | WIP/material per step | 1 | Done | 2026-03-21 | Domain, repo, migrate, seed P-001 |
| 2 | WIP inventory layer | 3 | Done | 2026-03-21 | WIPInventory domain, repo ListWIPByJobStepID, UpsertWIP |
| 3 | Time offset between steps | 1 | Done | 2026-03-21 | MinWaitMinutes, TransferMinutes on ProcessSteps |
| 4 | Batch / lot handling | 3 | Done | 2026-03-21 | BatchSize, MinBatchSize, IsBatchProcess on ProcessSteps |
| 5 | Setup / sequence dependency | 2 | Done | 2026-03-21 | MachineSetupRule, validateMachineWindow, earliestStartWithSetup |
| 6 | Resources beyond machine | 2 | Done | 2026-03-21 | Resource, StepResourceRequirement, ResourceCalendar, ResourceAllocation |
| 7 | Formula lead time | 1 | Done | 2026-03-21 | LeadTimeHours, Source on FormulaIngredients |
| 8 | Alternative routing | 2 | Done | 2026-03-21 | IsPrimary, Sequence on ProductProcess; ListProcessesByProductIDAsOf |
| 9 | Split strategy config | 3 | Done | 2026-03-21 | AI_SPLIT_STRATEGY feature flag |
| 10 | Global optimization objective | 3 | Done | 2026-03-21 | AI_OBJECTIVE feature flag |
| 11 | Event-based rescheduling | 3 | Done | 2026-03-21 | SchedulingEvent, POST /scheduling/events, AI_AUTO_RESCHEDULE_ON_EVENT |
| 12 | Slot model (actual, paused) | 3 | Done | 2026-03-21 | ActualStart, ActualEnd, SlotStatusPaused |
| 13 | Dependency graph (DAG) | 2 | Done | 2026-03-21 | PredecessorStepIDs, getPredecessorStepIDs, validateStepPrecedence |
| 14 | Constraint priority | 2 | Done | 2026-03-21 | ValidationReason, HardReasons, SoftReasons, TotalPenalty |
| 15 | Versioning (effective dates) | 1 | Done | 2026-03-21 | EffectiveFrom/To on Process, Formula; GetProcessByProductIDAsOf |
