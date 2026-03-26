Complete AI Function Plan

Goal

Turn the current AI-assisted scheduling backend into a production-ready AI function that can safely generate, review, explain, approve, apply, observe, and continuously improve schedule decisions.

Current Baseline

Already implemented:





Heuristic AI scheduling service in [c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\ai_scheduling_service.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\ai_scheduling_service.go)



NLP/API orchestration in [c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\handler\ai_handler.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\handler\ai_handler.go)



Scheduling substrate and feasibility rules in [c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_service.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_service.go) and [c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_support.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_support.go)



Solver-shaped normalization in [c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_preview_service.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_preview_service.go)



Public AI contract in [c:\Users\dilun\OneDrive\Documents\eMas APi\emas\API.md](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\API.md)

Main gap:





The system is strong at heuristic assist, but not yet complete as an enterprise AI function because it lacks a persisted proposal lifecycle, real optimizer/model integration, production-safe governance, and outcome feedback loops.

Target Architecture

flowchart TD
    Planner[PlannerUI] --> aiCommand[AICommandHandler]
    aiCommand --> readOnlyCards[ResultCards]
    aiCommand --> proposalApi[ProposalAPI]
    proposalApi --> proposalStore[ProposalStore]
    proposalApi --> heuristicEngine[HeuristicEngine]
    proposalApi --> solverAdapter[SolverAdapter]
    heuristicEngine --> schedulingCore[SchedulingCore]
    solverAdapter --> schedulingPreview[SolverPreviewBuilder]
    schedulingCore --> inventoryState[InventoryAndReservations]
    schedulingCore --> machineState[MachinesCalendarsDowntime]
    proposalStore --> approvalFlow[ApprovalAndApplyFlow]
    approvalFlow --> slotWriter[JobSlotService]
    approvalFlow --> auditLog[AuditAndMetrics]
    slotWriter --> executionData[ProductionLogsQCOutcomes]
    executionData --> trainingData[TrainingDatasetAndEvaluation]
    trainingData --> modelLoop[FutureMLAndPolicyTuning]

Phase 1: Make Proposal Workflow Enterprise-Safe

Purpose: no AI function is complete until proposal generation and application are safe, reviewable, and auditable.

Scope:





Introduce a first-class persisted proposal resource instead of using only transient proposal payloads.



Add proposal status lifecycle: draft, approved, rejected, applied, stale.



Store snapshot metadata: job state hash, engine version, generated inputs, summary, risk, and explanation.



Make apply flow transactional and idempotent.



Detect stale proposals when inventory, slot state, or machine state changed since generation.



Replace generic business-rule 500 responses with explicit 409 or 422 semantics where appropriate.

Main files:





[c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\ai_scheduling_service.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\ai_scheduling_service.go)



[c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\job_slot_service.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\job_slot_service.go)



[c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\router\router.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\router\router.go)



New domain/repository/handler files for proposal persistence

Success criteria:





A proposal can be created, reviewed, approved, and applied safely.



Concurrent planner activity cannot silently apply stale AI decisions.



Frontend can show proposal history and current status.

Phase 2: Add Governance, Auth, and Observability

Purpose: AI scheduling writes must be attributable and measurable.

Scope:





Replace placeholder auth in [c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\middleware\auth.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\middleware\auth.go) with real auth/RBAC for scheduler endpoints.



Require approval permission for proposal approval/apply.



Emit structured audit events for generate, approve, reject, apply, and rollback.



Add request correlation IDs and structured Zap logs around AI endpoints.



Add core metrics: proposal count, acceptance rate, apply failures, stale proposal rate, execution latency.

Main files:





[c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\middleware\auth.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\middleware\auth.go)



[c:\Users\dilun\OneDrive\Documents\eMas APi\emas\cmd\emas\main.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\cmd\emas\main.go)



AI handlers and services

Success criteria:





Every scheduling write is permission-checked and auditable.



AI decisions are observable in logs and metrics.

Phase 3: Upgrade Proposal Quality With Real Optimization

Purpose: move from heuristic-only planning to a solver-backed AI function.

Scope:





Define a solver adapter interface behind the existing preview model.



Use [c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_preview_service.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_preview_service.go) as the canonical input builder.



Add objective scoring: lateness, machine overload, changeover cost, split complexity, material-risk, setup waste.



Implement timeout budget and fallback to the current heuristic proposal engine.



Return explainable comparison fields: engine=heuristic|solver, objective score, fallback reason.

Main files:





[c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_preview_service.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_preview_service.go)



[c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\ai_scheduling_service.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\ai_scheduling_service.go)



New solver adapter package

Success criteria:





Proposal generation can use a true optimizer.



Heuristic remains as safe fallback.



API exposes which engine produced the proposal and why.

Phase 4: Improve NLP Into Real AI Orchestration

Purpose: the current regex parser is useful but brittle.

Scope:





Keep [c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\handler\ai_handler.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\handler\ai_handler.go) as the orchestration layer, but separate parsing from execution.



Introduce structured intent extraction service with confidence and ambiguity handling.



Support clarification responses when entity extraction is uncertain.



Preserve safe behavior: read-only execution in ai/command, explicit confirmation for write actions.



Keep result_cards as the stable frontend contract.

Success criteria:





Planner/operator phrasing becomes more robust.



Ambiguous commands do not silently execute the wrong thing.

Phase 5: Build Learning and Evaluation Loop

Purpose: complete AI requires feedback from actual operations, not just rules.

Scope:





Strengthen production outcome capture in [c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\production_log_service.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\production_log_service.go).



Capture accepted vs rejected proposals and eventual production outcomes.



Extend training export to include proposal metadata, actual completion, scrap, downtime, and deviation from estimate.



Add offline evaluation/backtesting datasets and baseline KPIs.

Main files:





[c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\production_log_service.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\production_log_service.go)



[c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_service.go](c:\Users\dilun\OneDrive\Documents\eMas APi\emas\internal\service\scheduling_service.go)

Success criteria:





You can compare proposed schedule quality against real plant outcomes.



Data becomes trustworthy enough for future ML ranking/risk models.

Phase 6: Production Rollout Strategy

Purpose: avoid turning on AI scheduling all at once.

Scope:





Add feature flags for heuristic-only, solver-preview, solver-shadow, and solver-default modes.



Run shadow evaluation first: generate solver proposals without applying them.



Compare acceptance, lateness, utilization, and planner overrides.



Only after stable metrics, allow default recommendation from solver-backed engine.

Success criteria:





You can measure whether AI is improving scheduling before making it authoritative.

Recommended Build Order





Proposal persistence and approval lifecycle



Transactional/idempotent/stale-safe apply flow



Auth, audit, and observability



Solver adapter with fallback



Better NLP orchestration



Outcome capture and evaluation loop



Controlled rollout with feature flags and shadow mode

Risks To Watch





Applying stale proposals after shop-floor conditions changed



Treating heuristic outputs as fully optimized schedules



Weak auth/audit on scheduling write paths



Training on inconsistent historical execution data



Frontend binding to raw insights instead of stable result_cards

Definition Of “AI Function Complete”

Treat the AI function as complete only when all of these are true:





It can generate useful proposals across realistic job mixes.



It can explain why a proposal was produced.



It can persist proposals and route them through approval.



It can apply approved plans safely and transactionally.



It is observable, permissioned, and auditable.



It can compare heuristic vs solver quality with measurable KPIs.



It has feedback data to improve future decision quality.

