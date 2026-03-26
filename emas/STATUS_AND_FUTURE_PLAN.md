# eMAS API — Current Status and Future Plan

## Current Status

### Core Platform ✅ Complete

- **Tech stack**: Go, Gin, GORM, MySQL (dev), SQLite (tests), Zap logging
- **18-table data model**: Products, Processes, Formulas, BOM, Jobs, JobSteps, Slots, Machines, Machine Capabilities/Calendar/Downtime, Inventory, Production Logs, Quality, Maintenance, AI Proposals
- **CRUD APIs** for all domains, reports, dashboard, reference data
- **API documentation**: `API.md` with endpoint specs, request/response shapes, and feature flag reference

### AI Scheduling — Implemented

| Component | Status | Notes |
|-----------|--------|-------|
| **Persisted proposal lifecycle** | ✅ Done | `AIProposal` entity with draft → approved → applied / rejected / stale; versioning, snapshot hash, outcome tracking |
| **Transactional apply** | ✅ Done | Idempotency keys, conflict checks, status gate before staleness |
| **Stale detection** | ✅ Done | Input hash comparison; proposals auto-marked stale when job/slot/inventory state changes |
| **Governance** | ✅ Done | Apply requires approval by default; compatibility endpoint deprecated; RBAC on write endpoints |
| **Solver adapter boundary** | ✅ Done | `ProposalEngineAdapter` interface; `PreviewSolverAdapter`, `RealSolverAdapter` |
| **Real optimizer (dispatch-ls-v1)** | ✅ Done | Greedy dispatch + local search; efficiency factors, machine timelines, weighted objective |
| **Heuristic engine** | ✅ Done | Earliest-start with parallel-split awareness; fallback when solver times out or fails |
| **NLP orchestration** | ✅ Done | Extracted to `AICommandOrchestrator`; confidence, ambiguity, clarifications, `result_cards` |
| **Shadow mode** | ✅ Done | Secondary engine runs and evidence stored on persisted proposals |
| **Rollout states** | ✅ Done | `heuristic-only`, `shadow`, `candidate-default`, `enforced-default` via `AI_ROLLOUT_STATE` |
| **Metrics & KPI** | ✅ Done | In-memory `AIMetrics`; persisted proposal counts; `GET /ai/metrics` with acceptance rate, deviation, rollout state |
| **Outcome capture** | ✅ Done | Production logs update `OutcomeJSON` on proposals; `EstimateDeviationMins`, `ActualProducedQty`, `ActualScrapQty` |
| **Training export** | ✅ Done | `TrainingDatasetRow` includes `ProposalID`, rollout state, estimate deviation |

### Auth & Observability

- **RBAC**: `X-User-Id`, `X-User-Role`; `RequireRoles` middleware on proposal approve/reject/apply
- **Request context**: `X-Request-Id`, structured Zap logs
- **Feature flags**: `AI_AUTH_REQUIRED`, `AI_PROPOSAL_ENGINE`, `AI_SOLVER_SHADOW_MODE`, `AI_SOLVER_TIMEOUT_MS`, `AI_COMPAT_APPLY_ENABLED`, `AI_PROPOSAL_APPLY_REQUIRES_APPROVAL`, `AI_ROLLOUT_STATE`, `AI_SOLVER_KPI_GATE`

### Known Gaps

- **Auth**: Header-trust only; no real token or session auth
- **KPI persistence**: Metrics derived from DB aggregates; no separate evaluation/backtesting tables or endpoints
- **External solver**: Real-solver is in-process Go; no OR-Tools / CP-SAT or external optimizer yet

---

## Future Plan

### Short-term (Next Sprint)

1. **Backtesting / KPI endpoint**  
   Add `GET /ai/scheduling/evaluation` (or similar) that returns persisted aggregates: acceptance rate, stale rate, apply failure rate, average estimate deviation, scrap by engine. Optionally persist daily snapshots for trend analysis.

2. **Real authentication**  
   Replace header-trust with JWT or session-based auth; integrate with existing RBAC middleware.

3. **Frontend integration**  
   - Wire `POST /ai/command` response (`result_cards`, `suggested_calls`) into the planner UI  
   - Implement proposal lifecycle UI: generate → approve/reject → apply  
   - Show engine, objective score, and rollout state in proposal cards  

### Medium-term (Next Quarter)

4. **OR-Tools / external solver**  
   - Add a new adapter (e.g. `ORToolsSolverAdapter`) that calls a Python microservice or gRPC server running CP-SAT  
   - Keep `real-solver` as the default in-process option; OR-Tools as opt-in via `AI_PROPOSAL_ENGINE=ortools`  
   - Expose solver timeout and fallback behaviour in API docs  

5. **Global multi-job optimizer (optional enhancement)**  
   - Current batch flow uses sequential scheduling (EDD/EPO). Optional future: true joint optimization (OR-Tools CP-SAT, genetic algo) where all job steps are in one model.  

6. **ML ranking / risk models**  
   - Use training export and outcome data to train models for:  
     - Machine ranking  
     - Delay risk prediction  
     - Split suggestions  
   - Run models in shadow mode before promoting to production.  

### Long-term (Roadmap)

7. **ERP/MES integration**  
   - Sync inventory, production orders, and equipment status from external systems  
   - Webhooks or polling for real-time state updates  

8. **Explainability**  
   - Richer reasoning in proposal slots (why this machine, why this start time)  
   - Visualisation support for precedence and capacity constraints  

9. **Policy / BDI agents**  
   - Higher-level policy rules (e.g. “never schedule on machine X after 4pm”)  
   - BDI-style agents for escalation and exception handling  

---

## Success Criteria for “AI Function Complete”

- [x] Generate useful proposals across realistic job mixes  
- [x] Explain why a proposal was produced (engine, score, reasoning)  
- [x] Persist proposals and route through approval  
- [x] Apply approved plans safely and transactionally  
- [x] Observable, permissioned, auditable  
- [x] Compare heuristic vs solver quality with measurable KPIs  
- [x] Feedback data (outcome capture, training export) for improvement  
- [ ] Real authentication (not header-trust)  
- [ ] External solver integration (optional, for advanced use cases)  

---

## References

- **API contract**: `API.md`
- **Original plan**: `internal/plan.md`
- **Scheduling analysis**: `SCHEDULING_COMPLEXITY_ANALYSIS.md`
