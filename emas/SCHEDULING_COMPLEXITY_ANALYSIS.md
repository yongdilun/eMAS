# Scheduling Complexity Analysis

## Scope
This document analyzes the current `eMas` backend from the perspective of AI-assisted scheduling and optimization.

The analysis focuses on:

- All database-backed attributes that can affect scheduling decisions
- Nested product structures where a product consumes other products
- Inventory sufficiency and future expected arrivals
- Earliest feasible start and completion logic
- Split execution, including partial completion over multiple time windows
- Parallel execution of the same product or step across multiple machines
- Data-model risks and gaps that matter before training an AI model

## Executive Summary
The current system already contains many of the core entities needed for an AI scheduler:

- products
- product process and process steps
- jobs, job steps, and scheduled slots
- machines and machine capabilities
- machine downtime and maintenance
- raw-material inventory
- expected future material arrivals
- nested BOM / formula structures
- production logs and quality records

However, the system is not yet a fully reliable scheduling ground truth for AI training.

The biggest strengths are:

- explicit process routing per product
- explicit slot-level scheduling records
- machine-to-step capability mapping
- support for nested sub-products
- support for future material arrivals
- the ability to split a job step into multiple scheduled slots

The biggest risks are:

- two parallel composition models (`product_bom` and `formula_ingredients`) with no canonical source of truth
- no finished-goods or WIP inventory for sub-products
- no reservation model for time-phased inventory commitment
- no overlap constraints for machine bookings
- weak status semantics for partial completion
- synthetic job steps can be created without a real `step_id` when jobs are created with inline slots

If you want to train an AI scheduler, the backend is already good enough for:

- rule-based heuristics
- feasibility filtering
- earliest-start estimation
- machine ranking
- simple dispatch optimization

It is not yet ideal for:

- high-confidence optimal scheduling
- multi-level ATP/CTP
- realistic promise dates for nested assemblies
- clean supervised learning from historical labels

## Scheduling-Relevant Tables And Attributes

### 1. `products`
Purpose: master record for each make item or sub-product.

Important fields:

- `product_id`: primary identity for scheduling
- `product_name`: display only, but important for human validation
- `description`: low direct scheduling impact
- `unit_of_measure`: affects interpretation of quantity
- `product_type`: can be useful as a feature
- `status`: active vs obsolete
- `formula_id`: direct link to product formula
- `created_at`: weak scheduling impact

Scheduling role:

- selects the routing through `product_process`
- selects the composition through `formula_id` and/or `product_bom`
- acts as a parent or sub-product in nested manufacturing

Complexity note:

- this table now supports `formula_id`, which is useful for frontend and model feature engineering

### 2. `product_process`
Purpose: routing header for how a product is manufactured.

Important fields:

- `process_id`
- `product_id`
- `process_name`
- `version`
- `description`

Scheduling role:

- defines which routing version is used for job-step generation

Complexity note:

- the repository resolves process by highest version
- there is no explicit "active version" or effective-date control

### 3. `process_steps`
Purpose: ordered operations for a routing.

Important fields:

- `step_id`
- `process_id`
- `step_sequence`
- `step_name`
- `step_type`
- `machine_type_required`
- `default_preparation_time`
- `default_processing_time`
- `default_cleaning_time`
- `default_changeover_time`
- `quality_check_required`
- `notes`

Scheduling role:

- gives operation precedence through `step_sequence`
- defines base duration
- defines what kind of machine is needed
- indicates whether QC is required after the step

Complexity note:

- `step_type` is now useful for grouping and feature engineering
- precedence is strictly linear in the current schema
- there is no explicit support for branching or overlap constraints between steps

### 4. `jobs`
Purpose: production orders.

Important fields:

- `job_id`
- `product_id`
- `quantity_total`
- `quantity_completed`
- `priority`
- `deadline`
- `status`
- `created_at`
- `updated_at`
- `notes`

Scheduling role:

- defines the demand unit to be scheduled
- provides the objective signals: due date and priority
- tracks progress

Complexity note:

- there is no explicit `release_at`, `earliest_start`, `customer_priority_score`, or penalty model

### 5. `job_steps`
Purpose: instantiated routing steps for a specific job.

Important fields:

- `job_step_id`
- `job_id`
- `step_id`
- `step_sequence`
- `quantity_target`
- `quantity_completed`
- `status`

Scheduling role:

- represents the real execution stages for a job
- is the main parent for slot splitting

Complexity note:

- this is the key table for modeling partial completion
- current design allows progress accumulation, but not strong semantics for partial vs final allocation

### 6. `job_step_schedule_slots`
Purpose: actual planned schedule blocks on machines.

Important fields:

- `slot_id`
- `job_step_id`
- `machine_id`
- `scheduled_start`
- `scheduled_end`
- `quantity_planned`
- `preparation_time_minutes`
- `processing_time_minutes`
- `cleaning_time_minutes`
- `changeover_time_minutes`
- `buffer_time_minutes`
- `status`

Scheduling role:

- is the true schedule output table
- supports splitting one step across multiple slots
- supports assigning the same step to multiple machines

Complexity note:

- this table already makes parallel execution possible
- there is no database constraint preventing machine double-booking

### 7. `machines`
Purpose: machine master data.

Important fields:

- `machine_id`
- `machine_name`
- `machine_type`
- `location`
- `status`
- `capacity_per_hour`
- `default_setup_time`
- `default_cleaning_time`
- `default_changeover_time`
- `utilization_rate`
- `last_maintenance_date`
- `maintenance_interval_days`

Scheduling role:

- defines machine availability and machine family
- supports rough duration estimation
- supports maintenance risk signals

Complexity note:

- `utilization_rate` is a helpful feature, but it is not an allocation constraint

### 8. `machine_capabilities`
Purpose: explicit machine-step eligibility.

Important fields:

- `capability_id`
- `machine_id`
- `step_id`
- `efficiency_factor`

Scheduling role:

- determines whether a machine can run a specific step
- modifies effective throughput via `efficiency_factor`

Complexity note:

- this is one of the most important tables for AI scheduling
- capability is defined at exact step level, not generic family level

### 9. `machine_calendar`
Purpose: working and blocked time windows.

Important fields:

- `calendar_id`
- `machine_id`
- `start_time`
- `end_time`
- `availability_type`
- `shift_name`

Scheduling role:

- should define work windows and unavailable periods

Complexity note:

- structurally useful, but current scheduling services do not appear to actively consume it
- if you want AI scheduling to reflect shifts, this table must become operationally enforced

### 10. `machine_downtime`
Purpose: actual breakdown or interruption periods.

Important fields:

- `downtime_id`
- `machine_id`
- `job_step_slot_id`
- `cause`
- `start_time`
- `end_time`
- `duration_minutes`

Scheduling role:

- affects short-term machine feasibility
- should block slot execution during breakdown periods

### 11. `maintenance_records`
Purpose: maintenance events.

Important fields:

- `maintenance_id`
- `machine_id`
- `maintenance_type`
- `technician`
- `start_time`
- `end_time`
- `description`

Scheduling role:

- influences machine capacity and future risk

### 12. `inventory_materials`
Purpose: current raw-material inventory.

Important fields:

- `material_id`
- `material_name`
- `unit`
- `current_stock`
- `min_stock`
- `reorder_level`
- `storage_location`
- `status`
- `last_updated`

Scheduling role:

- drives immediate material feasibility
- low stock and reorder thresholds can be used as soft penalties

### 13. `inventory_transactions`
Purpose: historical material movement.

Important fields:

- `transaction_id`
- `material_id`
- `transaction_type`
- `quantity`
- `reference_job_id`
- `timestamp`
- `notes`

Scheduling role:

- provides history for consumption and replenishment trends

Complexity note:

- material consumption is tracked at job level, not robustly at slot level

### 14. `inventory_expected_arrivals`
Purpose: future inbound raw-material supply.

Important fields:

- `arrival_id`
- `material_id`
- `quantity`
- `expected_arrive_at`
- `status`
- `notes`
- `reference_job_id`
- `received_at`
- `created_at`

Scheduling role:

- enables future-feasible scheduling
- allows shortage-aware earliest-start estimation

Complexity note:

- this is a very important addition for AI-based scheduling
- expected arrivals currently exist only for raw materials, not sub-products

### 15. `product_bom`
Purpose: product material and sub-product composition.

Important fields:

- `bom_id`
- `product_id`
- `component_type`
- `material_id`
- `product_component_id`
- `quantity_required`
- `unit`
- `scrap_rate`

Scheduling role:

- one source for recursive material explosion
- supports nested product structure

### 16. `formula`
Purpose: recipe header.

Important fields:

- `formula_id`
- `formula_name`
- `version`
- `instructions`
- `safety_notes`
- `created_at`

Scheduling role:

- may represent the canonical recipe for material feasibility

### 17. `formula_ingredients`
Purpose: recipe line items, raw materials or sub-products.

Important fields:

- `ingredient_id`
- `formula_id`
- `component_type`
- `material_id`
- `product_id`
- `quantity_per_unit`
- `unit`
- `scrap_rate`
- `percentage`

Scheduling role:

- supports recursive product explosion
- can be used to compute gross material demand

Complexity note:

- this overlaps conceptually with `product_bom`
- duplicate protection now exists at service level, which improves data quality

### 18. `production_logs`
Purpose: actual output logged against slots.

Important fields:

- `production_id`
- `slot_id`
- `start_time`
- `end_time`
- `quantity_produced`
- `quantity_scrap`
- `operator_notes`

Scheduling role:

- is the strongest actual-execution signal
- drives update of `job_steps.quantity_completed`
- drives update of `jobs.quantity_completed`

Complexity note:

- current service marks slot completed after a production log, even if only partial production was done

### 19. `quality_inspection_records`
Purpose: QC output after steps.

Important fields:

- `inspection_id`
- `job_step_id`
- `inspection_time`
- `inspector_name`
- `result`
- `defect_count`
- `notes`

Scheduling role:

- should influence downstream step release and rework logic

Complexity note:

- QC exists, but release-block semantics are not enforced in the scheduling layer

## Nested Product Complexity

The seed already proves that nested manufacturing is part of the domain.

Current examples:

- `P-001` uses `P-007` and `P-008`
- `P-004` uses `P-007`
- `P-006` uses `P-003` and `P-009`

This means parent-product scheduling is not only a machine-routing problem. It is also a recursive dependency problem.

### Why nesting matters
If `P-001` needs `P-007` and `P-008`, then scheduling `P-001` requires answering:

- do we already have those sub-products available?
- if not, do we need to manufacture them first?
- what machines and steps are needed for those child products?
- what raw materials are needed for the child products?
- when will all child requirements be ready?

This turns the scheduling problem into a multi-level production graph.

### Practical implication
The true parent ready time becomes:

`parent_ready_time = max(all_child_ready_times, all_raw_material_ready_times, predecessor_step_ready_time, machine_ready_time)`

## Inventory Feasibility Analysis

### Immediate feasibility
For a job of quantity `Q`, raw-material feasibility requires recursive demand explosion.

For each formula or BOM item:

- if it is a raw material:
  - `required_material = Q * quantity_per_unit * (1 + scrap_rate)`
- if it is a sub-product:
  - compute child product demand recursively

### Recursive explosion
Pseudo-logic:

```text
GrossDemand(product, qty):
  for each component in CanonicalRecipe(product):
    if component is material:
      add qty * component_qty * (1 + scrap) to material demand
    if component is sub-product:
      GrossDemand(child_product, qty * component_qty * (1 + scrap))
```

### Key difficulty
The backend stores both:

- `product_bom`
- `formula_ingredients`

For AI scheduling, one of these must become the canonical source for demand explosion.

If both are used without a rule, the training data becomes ambiguous.

### Current limitation
There is no true inventory table for finished or semi-finished products.

That means the system cannot directly answer:

- how many `P-007` are already on hand?
- how many `P-003` are already available as sub-assemblies?
- how many `P-009` are in WIP and nearly done?

This is one of the biggest blockers for accurate nested scheduling.

## Expected Arrival Time Analysis

The new `inventory_expected_arrivals` table improves scheduling because shortages can now become future-feasible.

### Earliest material ready time
Let:

- `D` = required quantity of a material
- `S0` = current stock
- `Arrivals(t)` = cumulative pending arrival quantity up to time `t`

Then:

- if `S0 >= D`, material is ready now
- otherwise, material ready time is the earliest `t` such that:

`S0 + Arrivals(t) >= D`

### Earliest product ready time
For a parent product, material readiness is not enough. You must combine:

- raw material ready time
- sub-product ready time
- predecessor step completion time
- machine availability
- downtime / maintenance constraints

A useful planning equation is:

`earliest_start(step_k) = max(predecessor_finish, material_ready, child_product_ready, machine_ready)`

## Split Execution And Partial Completion

The current schema already supports splitting one job step into multiple slots.

That means a step can be:

- partially run now
- paused
- resumed later
- assigned across multiple windows
- assigned across multiple machines

### What already works
Each slot stores:

- machine
- start/end time
- planned quantity
- separate prep/processing/cleaning/buffer times

This is enough to model:

- 50% now and 50% later
- 30/30/40 splits
- any variable split ratio

### Recommended split calculation
For a job step target quantity `T`, define split ratios:

- `r1, r2, ..., rn`

subject to:

`sum(ri) = 1.0`

Then:

`slot_quantity_i = T * ri`

Examples:

- 50% + 50%
- 20% + 30% + 50%
- 10% + 15% + 25% + 50%

### Current model gap
The database does not explicitly store:

- split percentage
- split intent
- batch grouping
- whether the split is sequential or parallel

It only stores `quantity_planned`, so the split must be inferred.

### Training implication
For AI training, quantity fields are more reliable than slot status labels.

Reason:

- `production_logs` increments quantity completed
- but current service marks slots completed immediately after any production log
- this can create noisy labels for partial execution

## Parallel Machine Execution

The current model does support parallelization of one product or step across multiple machines, at least structurally.

This happens when:

- multiple slots share the same `job_step_id`
- those slots use different `machine_id`
- those slots overlap in time or run in separate windows

### What is already present

- `job_step_schedule_slots`
- `machine_capabilities`
- `machines.capacity_per_hour`
- per-slot planned quantity

### What is missing

- no machine overlap prevention
- no machine concurrent-capacity flag
- no explicit "parallelizable step" boolean
- no transfer-batch size
- no minimum batch size per split
- no setup matrix by previous product / family

### Scheduling rule you will likely need
Parallel execution should only be allowed if:

- machine capability exists for that step
- machine is available in that time window
- the total split quantity does not exceed the step target
- step semantics allow parallel work

Useful constraint:

`sum(quantity_planned across active slots for a step) <= quantity_target`

## Attributes That Most Strongly Affect Scheduling

If you were building features for an AI model today, the most important columns are:

### Order / demand features

- `jobs.product_id`
- `jobs.quantity_total`
- `jobs.quantity_completed`
- `jobs.priority`
- `jobs.deadline`
- `jobs.status`

### Routing features

- `product_process.product_id`
- `product_process.version`
- `process_steps.step_sequence`
- `process_steps.step_type`
- `process_steps.machine_type_required`
- `process_steps.default_preparation_time`
- `process_steps.default_processing_time`
- `process_steps.default_cleaning_time`
- `process_steps.default_changeover_time`
- `process_steps.quality_check_required`

### Machine features

- `machines.machine_type`
- `machines.status`
- `machines.capacity_per_hour`
- `machines.default_setup_time`
- `machines.default_cleaning_time`
- `machines.default_changeover_time`
- `machines.utilization_rate`
- `machines.last_maintenance_date`
- `machines.maintenance_interval_days`
- `machine_capabilities.efficiency_factor`

### Time-window features

- `job_step_schedule_slots.scheduled_start`
- `job_step_schedule_slots.scheduled_end`
- `job_step_schedule_slots.quantity_planned`
- `job_step_schedule_slots.status`
- `machine_calendar.start_time`
- `machine_calendar.end_time`
- `machine_calendar.availability_type`
- `machine_downtime.start_time`
- `machine_downtime.end_time`
- `maintenance_records.start_time`
- `maintenance_records.end_time`

### Material features

- `inventory_materials.current_stock`
- `inventory_materials.min_stock`
- `inventory_materials.reorder_level`
- `inventory_materials.status`
- `inventory_expected_arrivals.quantity`
- `inventory_expected_arrivals.expected_arrive_at`
- `inventory_expected_arrivals.status`

### Recursive composition features

- `products.formula_id`
- `formula_ingredients.component_type`
- `formula_ingredients.material_id`
- `formula_ingredients.product_id`
- `formula_ingredients.quantity_per_unit`
- `formula_ingredients.scrap_rate`
- `product_bom.component_type`
- `product_bom.material_id`
- `product_bom.product_component_id`
- `product_bom.quantity_required`
- `product_bom.scrap_rate`

### Progress / execution features

- `job_steps.quantity_target`
- `job_steps.quantity_completed`
- `production_logs.quantity_produced`
- `production_logs.quantity_scrap`
- `quality_inspection_records.result`
- `quality_inspection_records.defect_count`

## Critical Data Risks Before AI Training

### 1. Canonical composition ambiguity
There are two composition sources:

- `product_bom`
- `formula_ingredients`

Before training, choose one as the source of truth for scheduling and material explosion.

### 2. No sub-product inventory
Without a finished-goods or WIP inventory table for products, nested feasibility is incomplete.

Recommended addition:

- `product_inventory`
- or `wip_inventory`

Suggested fields:

- `product_id`
- `quantity_on_hand`
- `quantity_reserved`
- `available_from`
- `storage_location`
- `last_updated`

### 3. No reservation model
Current stock is global stock, not time-phased committed stock.

Recommended addition:

- `inventory_reservations`

Suggested fields:

- `reservation_id`
- `material_id`
- `job_id`
- `job_step_id`
- `reserved_qty`
- `needed_at`
- `status`

### 4. Slot overlap is not constrained
Two slots can be placed on the same machine at the same time.

This is dangerous for:

- optimization
- simulation
- AI label quality

### 5. Ad hoc job-step creation risk
If a job is created with inline slots, the service may create synthetic `job_steps` with no real `step_id`.

This is a major training risk because:

- some job steps are routing-based
- some are ad hoc placeholders

These should be separated or normalized before training.

### 6. Weak partial completion semantics
`production_logs` are useful, but slot status is noisy.

For AI training:

- trust actual quantities more than status strings

### 7. No explicit parallelization policy
The schema allows parallel slot creation, but it does not say when parallelism is valid.

Recommended addition on `process_steps`:

- `allow_parallel_execution`
- `min_split_qty`
- `max_parallel_machines`
- `transfer_batch_size`

## AI-Engineering Recommendations

### Minimum cleanup before training

1. Choose one composition source:
   - preferably `formula_ingredients` if you want product-linked formulas
   - or `product_bom` if you want a classic manufacturing BOM

2. Remove or normalize synthetic job steps created without `step_id`.

3. Add machine-overlap validation at the service or DB layer.

4. Treat quantity fields as ground truth, not status fields.

5. Build a recursive product-explosion pipeline before feature generation.

### Strongly recommended schema upgrades

1. Add product/sub-product inventory or WIP inventory.
2. Add inventory reservations.
3. Add explicit step dependency features beyond linear sequence.
4. Add parallelization controls to `process_steps`.
5. Add effective-date / active-version rules for processes and formulas.
6. Make `machine_calendar` part of actual scheduling enforcement.

### Recommended AI problem framing
Before training a single end-to-end AI scheduler, split the problem into smaller models or solvers:

1. Feasibility engine
   - material readiness
   - sub-product readiness
   - machine eligibility

2. Earliest-start estimator
   - machine + material + dependency availability

3. Slot allocation / split optimizer
   - how much quantity to allocate to which machine and when

4. Dispatch ranker
   - which feasible job step to schedule next

This staged approach will be much more stable than trying to learn everything from raw tables at once.

## Final Verdict
The current backend is a strong starting point for scheduling research, but not yet a complete AI scheduling ground-truth system.

It is already capable of representing:

- product routing
- nested products
- machine assignment
- split slots
- future raw-material arrivals
- actual production progress

But for professional AI training, the highest-priority missing capabilities are:

- canonical product composition
- sub-product inventory
- reservation logic
- overlap-safe machine scheduling
- explicit split and parallelization semantics

Until those are tightened, the best use of AI is:

- decision support
- feasibility prediction
- heuristic ranking
- earliest-start estimation

rather than fully autonomous optimal scheduling.
