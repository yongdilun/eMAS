# Scheduler Evaluation Pipeline

The scheduler evaluator turns schedule output into a versioned scorecard. It is backend-first and does not use Factory Agent, chat prompts, approvals, or browser state.

## Run The Full Suite

```powershell
go run ./cmd/scheduler_eval -scenario all -endpoint both -use-memory-db -compare-schedulers -timeout 180s -json-out test-results/scheduler-eval/report.json -markdown-out test-results/scheduler-eval/report.md
```

`-use-memory-db` runs each scenario in a fresh in-memory database, so scenarios do not contaminate each other.

## Scheduler Versions

The evaluator can run named scheduler profiles on identical scenario fixtures:

- `v1-current`: current priority/deadline order, mapped to `order_by=epo`.
- `v2-material-aware-priority`: priority-first order that uses material readiness before deadline inside the same priority, mapped to `order_by=material_priority`.
- `v3-weighted-tardiness-material`: age/material-pressure order that treats older released jobs as higher tardiness risk, mapped to `order_by=weighted_tardiness_material`.
- `v4-product-deadline-fifo`: FIFO/material order that pulls tighter-deadline work forward inside the same product family, mapped to `order_by=product_deadline_fifo`.

Use `-compare-schedulers` or `-scheduler-version all` to run all known profiles and emit `version_diffs`.

Run only one profile when you want a stable baseline:

```powershell
go run ./cmd/scheduler_eval -scenario all -endpoint both -use-memory-db -scheduler-version v1-current -timeout 180s -json-out test-results/scheduler-eval/v1.json -markdown-out test-results/scheduler-eval/v1.md
```

Compare a candidate against that baseline:

```powershell
go run ./cmd/scheduler_eval -scenario all -endpoint both -use-memory-db -scheduler-version v2-material-aware-priority -baseline-json test-results/scheduler-eval/v1.json -timeout 180s -json-out test-results/scheduler-eval/v2.json -markdown-out test-results/scheduler-eval/v2.md
```

## Hard Gates

CI fails only on correctness and material semantics:

- machine overlaps
- invalid time ranges
- duplicate slots
- step order violations
- feasible proposals without slots
- infeasible proposals without reason/evidence
- material shortage evidence missing for shortage-blocked work
- skipped/silently excluded scheduler inputs

## Quality Metrics

Quality is report-only until thresholds stabilize:

- overall score
- quality score
- late jobs
- total and max tardiness
- top late jobs, sorted by worst tardiness first
- makespan
- machine utilization
- wait time
- setup switches
- runtime and jobs per second
- schedule hash, endpoint diffs, and scheduler version diffs

## Scenarios

- `canonical_seed`: exact canonical seed data, broad baseline.
- `true_material_shortage`: only affected jobs should be infeasible with material evidence.
- `delayed_material_wait`: future material arrival should cause waiting, not false infeasible.
- `child_bom_shortage`: parent shortage traces to child raw material.
- `no_shortage_control`: enough material and capacity.
- `resource_overload`: resource pressure should not become material shortage.
- `one_shot_resolution`: apply recommended material rows, rerun, and require no remaining material infeasible jobs.

## Reading Results

Correctness score below 100 means the schedule is invalid or semantically unsafe.
Quality score below 100 means the schedule is valid but has optimization weakness. For example, a canonical seed run can pass hard gates while still showing many late jobs and high tardiness.

When comparing scheduler versions, check both total tardiness and max tardiness. A candidate that lowers total tardiness but increases the worst single job may still be risky for planners. The Markdown report prints top late jobs so the next optimization target is visible without opening the JSON.
