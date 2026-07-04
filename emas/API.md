# eMAS API Reference

Base URL: `http://localhost:8080/api/v1`

---

## Response Wrapper

All responses use this structure:

| Field | Type | Description |
|-------|------|-------------|
| `success` | `boolean` | Whether the request succeeded |
| `data` | `object` \| `array` | Response payload (omit on error) |
| `error` | `string` | Error message when `success` is `false` |

---

## Jobs

### POST /jobs

Create a new job.

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `product_id` | `string` | Yes | Product identifier |
| `quantity_total` | `integer` | Yes | Target quantity (> 0) |
| `priority` | `string` | No | Priority level (`low` \| `medium` \| `high` \| `urgent`) |
| `deadline` | `string` | No | ISO 8601 / RFC3339 datetime |
| `notes` | `string` | No | Notes |
| `slots` | `array` | No | Initial slots (see `CreateSlotRequest`) |

**CreateSlotRequest (for `slots` items)**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `machine_id` | `string` | Yes | Machine identifier |
| `start_time` | `string` | Yes | RFC3339 datetime |
| `duration_mins` | `integer` | Yes | Duration in minutes (> 0) |
| `quantity` | `integer` | Yes | Quantity for slot (> 0) |
| `job_step_id` | `string` | No | Job step ID (for split) |
| `split_group_id` | `string` | No | Logical split group identifier |
| `allocation_percent` | `number` | No | Percent of job-step quantity allocated to this slot |
| `is_parallel` | `boolean` | No | Whether this slot runs in parallel with siblings |
| `batch_sequence` | `integer` | No | Batch order inside the split group |
| `prep_mins` | `integer` | No | Prep time (mins) |
| `processing_mins` | `integer` | No | Processing time |
| `cleaning_mins` | `integer` | No | Cleaning time |
| `buffer_mins` | `integer` | No | Buffer time |

**Response (201)** `data`: `JobResponse`

| Field | Type |
|-------|------|
| `job_id` | `string` |
| `product_id` | `string` |
| `quantity_total` | `integer` |
| `quantity_completed` | `integer` |
| `priority` | `string` (`low` \| `medium` \| `high` \| `urgent`) |
| `deadline` | `string` (RFC3339) |
| `status` | `string` |
| `created_at` | `string` (RFC3339) |
| `updated_at` | `string` (RFC3339) |
| `notes` | `string` |
| `steps` | `JobStepResponse[]` (optional) |
| `slots` | `SlotResponse[]` (optional) |

---

### GET /jobs

List jobs with optional filters.

**Query Parameters**

| Name | Type | Description |
|------|------|-------------|
| `product_id` | `string` | Filter by product |
| `status` | `string` | Filter by status |
| `priority` | `string` | Filter by priority |
| `machine_id` | `string` | Filter by machine |
| `start` | `string` | RFC3339 start date |
| `end` | `string` | RFC3339 end date |
| `sort_by` | `string` | `created_at` \| `deadline` \| `priority` \| `quantity_total` \| `completion` (default: `created_at`) |
| `sort_dir` | `string` | `asc` \| `desc` (default: `desc`) |
| `limit` | `integer` | Page size |
| `offset` | `integer` | Offset |

**Response (200)** `data`: `JobResponse[]`

---

### GET /jobs/:id

Get a job by ID.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Response (200)** `data`: `JobResponse`

**Response (404)** Not found

---

### GET /jobs/:id/steps

List steps for a job.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Response (200)** `data`: `JobStepResponse[]`

| Field | Type |
|-------|------|
| `job_step_id` | `string` |
| `job_id` | `string` |
| `step_id` | `string` |
| `step_sequence` | `integer` |
| `quantity_target` | `integer` |
| `quantity_completed` | `integer` |
| `status` | `string` |

---

### GET /jobs/:id/slots

List slots for a job.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Response (200)** `data`: `SlotResponse[]`

| Field | Type |
|-------|------|
| `slot_id` | `string` |
| `job_step_id` | `string` |
| `machine_id` | `string` |
| `scheduled_start` | `string` (RFC3339) |
| `scheduled_end` | `string` (RFC3339) |
| `quantity_planned` | `integer` |
| `split_group_id` | `string` |
| `allocation_percent` | `number` |
| `is_parallel` | `boolean` |
| `batch_sequence` | `integer` |
| `status` | `string` |

---

### PUT /jobs/:id

Update a job.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Request Body** (all optional)

| Field | Type |
|-------|------|
| `quantity_total` | `integer` |
| `priority` | `string` |
| `deadline` | `string` (RFC3339) |
| `status` | `string` |
| `notes` | `string` |

**Response (200)** `data`: `JobResponse`

---

### DELETE /jobs/:id

Delete a job.
Also removes related job steps and clears all slot assignments for that job.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Response (200)** `success: true`, no `data`

---

### POST /jobs/:id/duplicate

Duplicate a job.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Request Body** (optional)

| Field | Type |
|-------|------|
| `deadline` | `string` (RFC3339) |
| `quantity` | `integer` |

**Response (201)** `data`: `JobResponse`

---

## Job Steps & Slots

### POST /job-steps

Create job steps from product routing.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `job_id` | `string` | Yes |

**Response (201)** `data`: `JobStepResponse[]`

---

### POST /job-steps/split

Split a step into multiple slots.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `job_step_id` | `string` | Yes |
| `splits` | `CreateSlotRequest[]` | Yes |

**Response (201)** `data`: `SlotResponse[]`

---

### GET /job-steps/:id/slots

List slots for a job step.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job step ID |

**Response (200)** `data`: `SlotResponse[]`

---

### GET /slots/:id

Get slot details.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – slot ID |

**Response (200)** `data`: `SlotResponse`

---

### PUT /slots/:id

Update a slot.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – slot ID |

**Request Body** (all optional)

| Field | Type |
|-------|------|
| `machine_id` | `string` |
| `scheduled_start` | `string` (RFC3339) |
| `scheduled_end` | `string` (RFC3339) |
| `quantity_planned` | `integer` |

**Response (200)** `data`: `SlotResponse`

---

### DELETE /slots/:id

Cancel a slot.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – slot ID |

**Response (200)** `success: true`, no `data`

---

## Machines

### POST /machines

Create a machine.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `machine_id` | `string` | Yes |
| `machine_name` | `string` | Yes |
| `machine_type` | `string` | Yes |
| `location` | `string` | No |
| `capacity_per_hour` | `integer` | No |
| `default_setup_time` | `integer` | No |
| `default_cleaning_time` | `integer` | No |
| `default_changeover_time` | `integer` | No |
| `maintenance_interval_days` | `integer` | No |

**Response (201)** `data`: machine object

---

### GET /machines

List all machines.

**Query Parameters**

| Name | Type | Description |
|------|------|-------------|
| `status` | `string` | Filter by status |
| `machine_name` | `string` | Case-insensitive contains filter by machine name |
| `machine_type` | `string` | Filter by machine type |
| `location` | `string` | Filter by location |
| `sort_by` | `string` | `machine_id`, `machine_name`, `status`, or `created_at` |
| `sort_dir` | `string` | `asc` or `desc` |
| `limit` | `integer` | Limit number of results |
| `offset` | `integer` | Offset for pagination |
| `fields` | `string` | Comma-separated fields to return |

**Response (200)** `data`: `Machine[]`

| Field | Type |
|-------|------|
| `machine_id` | `string` |
| `machine_name` | `string` |
| `machine_type` | `string` |
| `location` | `string` |
| `status` | `string` |
| `capacity_per_hour` | `integer` |
| `utilization_rate` | `number` |
| etc. | ... |

---

### GET /machines/utilization

Get machine utilization summary.

**Response (200)** `data`:

| Field | Type |
|-------|------|
| `avg_pct` | `number` |
| `data` | `array` of `{ machine_id: string, machine_name: string, utilization_pct: number }` |

---

### GET /machines/:id

Get a machine by ID.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – machine ID |

**Response (200)** `data`: machine object

---

### PUT /machines/:id

Update a machine.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – machine ID |

**Request Body** (all optional)

| Field | Type |
|-------|------|
| `machine_name` | `string` |
| `machine_type` | `string` |
| `location` | `string` |
| `status` | `string` |
| `capacity_per_hour` | `integer` |
| `default_setup_time` | `integer` |
| `default_cleaning_time` | `integer` |
| `default_changeover_time` | `integer` |
| `maintenance_interval_days` | `integer` |

**Response (200)** `data`: machine object

---

### POST /machines/:id/capabilities

Assign a capability to a machine.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – machine ID |

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `step_id` | `string` | Yes |
| `efficiency_factor` | `number` | No |

**Response (201)** `data`: capability object

---

### POST /machines/downtime

Record machine downtime.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `machine_id` | `string` | Yes |
| `cause` | `string` | No |
| `start_time` | `string` (RFC3339) | No |
| `end_time` | `string` (RFC3339) | No |
| `job_step_slot_id` | `string` | No |

**Response (201)** `data`: downtime record

---

### GET /machines/maintenance-alerts

Get machines due for maintenance.

**Query Parameters**

| Name | Type | Default |
|------|------|---------|
| `days_ahead` | `integer` | 7 |

**Response (200)** `data`: maintenance alert objects (machine_id, machine_name, due date, etc.)

**Note:** Uses MySQL-specific SQL; may return 500 on SQLite.

---

### GET /machines/reroute-recommendations

Get reroute suggestions when a machine is down.

**Query Parameters**

| Name | Type | Required |
|------|------|----------|
| `machine_id` | `string` | Yes |

**Response (200)** `data`: reroute recommendation objects

**Response (400)** Missing `machine_id`

---

## Process (UC-P01 routing)

### POST /processes

Create a process.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `process_id` | `string` | Yes |
| `product_id` | `string` | Yes |
| `process_name` | `string` | Yes |
| `version` | `integer` | No |
| `description` | `string` | No |

**Response (201)** `data`: process object

---

### GET /processes

List all processes.

**Response (200)** `data`: process array

---

### GET /processes/:id

Get a process by ID.

**Path Parameters** `id`: `string` (process ID)

**Response (200)** `data`: process object

---

### GET /products/:id/process

Get the process linked to a product.

**Path Parameters** `id`: `string` (product ID)

**Response (200)** `data`: process object

---

### GET /processes/:id/steps

List process steps.

**Path Parameters** `id`: `string` (process ID)

**Response (200)** `data`: process step array

---

### POST /processes/:id/steps

Add a step to a process.

**Path Parameters** `id`: `string` (process ID)

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `step_name` | `string` | Yes |
| `step_id` | `string` | No |
| `step_sequence` | `integer` | No |
| `machine_type_required` | `string` | No |
| `default_preparation_time` | `integer` | No |
| `default_processing_time` | `integer` | No |
| `default_cleaning_time` | `integer` | No |
| `default_changeover_time` | `integer` | No |
| `quality_check_required` | `boolean` | No |
| `notes` | `string` | No |

**Response (201)** `data`: process step object

---

### DELETE /processes/:id

Delete a process.

**Path Parameters** `id`: `string` (process ID)

**Response (200)** `success: true`, no `data`

---

## Formula (UC-P01)

### POST /formulas

Create a formula.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `formula_id` | `string` | Yes |
| `formula_name` | `string` | Yes |
| `version` | `integer` | No |
| `instructions` | `string` | No |
| `safety_notes` | `string` | No |

**Response (201)** `data`: formula object

---

### GET /formulas

List all formulas.

**Response (200)** `data`: formula array

---

### GET /formulas/:id

Get a formula by ID.

**Path Parameters** `id`: `string` (formula ID)

**Response (200)** `data`: formula object

---

### GET /formulas/:id/ingredients

List formula ingredients.

**Path Parameters** `id`: `string` (formula ID)

**Response (200)** `data`: ingredient array (material_id, quantity, unit, etc.)

---

### POST /formulas/:id/ingredients

Add an ingredient to a formula.

**Path Parameters** `id`: `string` (formula ID)

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `material_id` | `string` | Yes |
| `quantity` | `number` | Yes |
| `unit` | `string` | No |
| `percentage` | `number` | No |

**Response (201)** `data`: ingredient object

---

### DELETE /formulas/:id

Delete a formula.

**Path Parameters** `id`: `string` (formula ID)

**Response (200)** `success: true`, no `data`

---

## Products

### POST /products

Create a product.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `product_id` | `string` | Yes |
| `product_name` | `string` | Yes |
| `description` | `string` | No |
| `unit_of_measure` | `string` | No |
| `product_type` | `string` | No |

**Response (201)** `data`: product object

---

### GET /products

List products with optional filters, sorting, pagination, and field selection.

**Query Parameters** (all optional)

| Name | Type | Notes |
|------|------|-------|
| `status` | `string` | Filter by product status |
| `product_type` | `string` | Filter by product type |
| `sort_by` | `string` | `product_id` \| `product_name` \| `created_at` |
| `sort_dir` | `string` | `asc` \| `desc` |
| `limit` | `integer` | Page size |
| `offset` | `integer` | Offset |
| `fields` | `string` | Use `product_id` for ID-only result view |

**Response (200)** `data`: product array

---

### GET /products/:id

Get a product by ID.

**Path Parameters** `id`: `string` (product ID)

**Response (200)** `data`: product object

---

### PUT /products/:id/bom

Link BOM (Bill of Materials) to a product.

**Path Parameters** `id`: `string` (product ID)

**Request Body**

| Field | Type |
|-------|------|
| `formula_id` | `string` |
| `process_id` | `string` |
| `bom_items` | `BOMItem[]` |

**BOMItem**

| Field | Type | Required |
|-------|------|----------|
| `material_id` | `string` | Yes |
| `quantity_required` | `number` | Yes |
| `unit` | `string` | No |
| `scrap_rate` | `number` | No |

**Response (200)** `success: true`, no `data`

---

## Inventory

### POST /inventory/materials

Create a material.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `material_id` | `string` | Yes |
| `material_name` | `string` | Yes |
| `unit` | `string` | No |
| `current_stock` | `number` | No |
| `min_stock` | `number` | No |
| `reorder_level` | `number` | No |
| `storage_location` | `string` | No |

**Response (201)** `data`: material object

---

### GET /inventory/materials

List materials with filters.

**Query Parameters**

| Name | Type | Description |
|------|------|-------------|
| `status` | `string` | Filter by status |
| `q` | `string` | Search by name |
| `sort_by` | `string` | `material_name` \| `current_stock` \| `last_updated` |
| `sort_dir` | `string` | `asc` \| `desc` |
| `limit` | `integer` | Page size |
| `offset` | `integer` | Offset |

**Response (200)** `data`: material array

---

### GET /inventory/materials/:id

Get a material by ID.

**Path Parameters** `id`: `string` (material ID)

**Response (200)** `data`: material object

---

### POST /inventory/consume

Consume material from stock.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `material_id` | `string` | Yes |
| `quantity` | `number` | Yes (> 0) |
| `reference_job_id` | `string` | No |
| `slot_id` | `string` | No |

**Response (200)** `success: true`, no `data`

---

### POST /inventory/receive

Receive material into stock.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `material_id` | `string` | Yes |
| `quantity` | `number` | Yes (> 0) |

**Response (200)** `success: true`, no `data`

---

### POST /inventory/expected-arrivals

Schedule inventory expected to arrive on a future date.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `material_id` | `string` | Yes |
| `quantity` | `number` | Yes (> 0) |
| `expected_arrive_at` | `string` | Yes, RFC3339 datetime |
| `notes` | `string` | No |

**Response (201)** `data`: expected arrival object (`arrival_id`, `material_id`, `quantity`, `expected_arrive_at`, `status`)

---

### GET /inventory/expected-arrivals

List expected arrivals (default: pending only).

**Query Parameters**

| Name | Type | Description |
|------|------|-------------|
| `material_id` | `string` | Filter by material |
| `status` | `string` | `pending` \| `received` \| `cancelled` (default: `pending`) |
| `from` | `string` | RFC3339 start date filter |
| `to` | `string` | RFC3339 end date filter |

**Response (200)** `data`: expected arrival array

---

## Production & Quality

### POST /production-logs

Log production output for a slot.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `slot_id` | `string` | Yes |
| `start_time` | `string` (RFC3339) | No |
| `end_time` | `string` (RFC3339) | No |
| `quantity_produced` | `integer` | No |
| `quantity_scrap` | `integer` | No |
| `operator_notes` | `string` | No |

**Response (201)** `data`: production log record

---

### POST /quality/inspections

Record a quality inspection.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `job_step_id` | `string` | Yes |
| `inspector_name` | `string` | No |
| `result` | `string` | No – `pass` \| `fail` |
| `defect_count` | `integer` | No |
| `notes` | `string` | No |

**Response (201)** `data`: inspection record

---

## Maintenance

### POST /maintenance

Record a maintenance event.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `machine_id` | `string` | Yes |
| `maintenance_type` | `string` | No |
| `technician` | `string` | No |
| `description` | `string` | No |
| `start_time` | `string` (RFC3339) | No |
| `end_time` | `string` (RFC3339) | No |

**Response (201)** `data`: maintenance record

---

## Reports & Analytics

Report endpoints generate PDFs only. They accept optional filters:

| Query | Type | Description |
|-------|------|-------------|
| `start` | `string` | RFC3339 start date (default: 30 days ago) |
| `end` | `string` | RFC3339 end date (default: now) |
| `machine_id` | `string` | Optional machine filter where supported |
| `job_id` | `string` | Optional job filter where supported |
| `product_id` | `string` | Optional product filter where supported |
| `material_id` | `string` | Optional material filter for inventory trends |

---

### GET /reports/production-output

Production output PDF.

**Response (200)** `application/pdf`

---

### GET /reports/machine-utilization

Machine utilization PDF.

**Response (200)** `application/pdf`

---

### GET /reports/job-completion

Job completion PDF.

**Response (200)** `application/pdf`

---

### GET /reports/inventory-trends

Inventory trends PDF.

**Response (200)** `application/pdf`

---

### GET /reports/quality-trends

Quality trends PDF.

**Response (200)** `application/pdf`

---

### GET /reports/oee

OEE trends PDF.

**Query** `machine_id`, `shift` (optional).

**Response (200)** `application/pdf`

---

### GET /reports/bottlenecks

Bottlenecks PDF.

**Response (200)** `application/pdf`

---

### GET /reports/downtime

Downtime PDF.

**Response (200)** `application/pdf`

---

### GET /reports/maintenance-efficiency

Maintenance efficiency PDF.

**Response (200)** `application/pdf`

---

PDF success responses include:

- `Content-Type: application/pdf`
- `Content-Disposition: inline; filename="<report-type>-<start>-<end>.pdf"`

Validation failures return the standard JSON error envelope.

---

Production visualization uses JSON analytics endpoints, not report endpoints.

### GET /production-analytics/summary

Summary metrics for visualization cards.

**Response (200)** `data`: `{ total_output, total_scrap, scrap_rate, downtime_hours, avg_utilization_pct, total_jobs, completed_jobs, in_progress_jobs, scheduled_jobs }`

---

### GET /production-analytics/output

Production output rows.

**Response (200)** `data`: `{ slot_id, machine_id, job_id, product_id, date, quantity_planned, quantity_produced, quantity_scrap }[]`

---

### GET /production-analytics/machine-utilization

Machine utilization rows.

**Response (200)** `data`: `{ machine_id, machine_name, total_minutes, downtime_minutes, utilization_pct, slot_count }[]`

---

### GET /production-analytics/job-completion

Job completion rows.

**Response (200)** `data`: `{ job_id, slot_id, product_id, quantity_planned, quantity_produced, completion_pct }[]`

---

### GET /production-analytics/downtime

Downtime rows.

**Response (200)** `data`: `{ machine_id, cause, date, duration_minutes, downtime_hours, occurrence_count }[]`

---

## Dashboard

### GET /dashboard/kpis

Aggregated KPI metrics for the dashboard.

**Response (200)** `data`:

| Field | Type |
|-------|------|
| `oee_pct` | `number` |
| `oee_change` | `number` |
| `production_units` | `integer` |
| `production_change` | `number` |
| `downtime_hrs` | `number` |
| `downtime_change` | `number` |
| `utilization_pct` | `number` |
| `utilization_change` | `number` |

---

### GET /alerts

List alerts (maintenance, inventory, downtime).

**Query Parameters**

| Name | Type | Description |
|------|------|-------------|
| `status` | `string` | e.g. `active` (optional filter) |

**Response (200)** `data`: `{ type: string, title: string, time: string, machine_id?: string }[]`

---

## Predictive Analysis

### GET /predictive/high-risk-jobs

List high-risk jobs (delays, maintenance, load).

**Response (200)** `data`:

| Field | Type |
|-------|------|
| `job_id` | `string` |
| `machine_name` | `string` |
| `issue` | `string` |
| `risk_level` | `string` – `High` \| `Medium` \| `Low` |
| `risk_score` | `number` |
| `delay_minutes` | `integer` |

---

### GET /predictive/recommendations

AI-style recommendations.

**Response (200)** `data`:

| Field | Type |
|-------|------|
| `icon` | `string` |
| `title` | `string` |
| `action` | `string` |
| `severity` | `string` (optional) |

---

### GET /predictive/forecast

Forecast data for charts.

**Query Parameters**

| Name | Type | Default |
|------|------|---------|
| `type` | `string` | `delays` – `delays` \| `failures` |

**Response (200)** `data`:

| Field | Type |
|-------|------|
| `type` | `string` |
| `data` | `{ label: string, value: number }[]` |

---

### GET /predictive/confidence

Model confidence level.

**Response (200)** `data`:

| Field | Type |
|-------|------|
| `confidence_pct` | `number` |
| `model` | `string` |
| `last_trained` | `string` (RFC3339) |

---

## AI / NLP

### POST /ai/command

Parse natural language command and return structured orchestration guidance.

The endpoint supports two modes:

- default `suggest_only`: parse intent and return the next API calls to make
- optional `execute_readonly`: execute a safe read-only insight call for supported AI intents

Write actions are never executed from this endpoint. Commands like create, reschedule, consume, cancel, approve, reject, and apply-proposal still return guidance plus suggested calls only.

Safe read-only execution is currently supported for:

- schedule proposal requests
- job explanation requests
- delay-risk requests
- machine-ranking requests
- job-status lookup with `job_id`
- bottleneck forecast requests

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `query` | `string` | Yes |
| `execute_readonly` | `boolean` | No |

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `intent` | `string` | Parsed intent, e.g. `create_job`, `reschedule`, `propose_schedule` |
| `action` | `string` | Suggested application action |
| `entities` | `object` | Extracted key-value pairs |
| `confidence` | `number` | Heuristic parsing confidence from `0` to `1` |
| `ambiguous` | `boolean` | Whether the command should be clarified before auto-routing |
| `clarifications` | `string[]` | Follow-up prompts when more information is needed |
| `message` | `string` | Human-readable next-step hint |
| `execution_mode` | `string` | `suggest_only`, `executed_readonly`, `blocked_write_action`, or `readonly_execution_failed` |
| `executed` | `boolean` | Whether a safe read-only call was executed |
| `executed_call` | `object` | The read-only call that was executed, if any |
| `suggested_calls` | `array` | Suggested API calls for the frontend/agent to execute next |
| `insights` | `object` | Optional execution result for supported read-only actions |
| `guidance` | `string[]` | Optional planner or integrator guidance |
| `result_cards` | `array` | Normalized frontend-ready cards for executed insights or blocked write actions |

Additional write-intent orchestration supported in suggest mode:

- `approve_proposal`
- `reject_proposal`
- `apply_proposal` using either `job_id` or persisted `proposal_id`

Important governance note:

- job-based compatibility apply is deprecated and disabled by default
- the supported production flow is `POST /ai/scheduling/jobs/:id/proposals` -> `POST /ai/scheduling/proposals/:id/approve` -> `POST /ai/scheduling/proposals/:id/apply`

`result_cards[]` fields:

| Field | Type | Description |
|-------|------|-------------|
| `kind` | `string` | Stable card type such as `schedule_proposal`, `delay_risk`, `job_explanation`, `job_status`, `machine_ranking`, `bottleneck_forecast`, `approval_required` |
| `title` | `string` | UI card title |
| `tone` | `string` | Suggested display tone such as `positive`, `info`, `warning`, `critical` |
| `summary` | `string` | Main one-line summary |
| `metrics` | `array` | Label/value metrics ready for chips or stat rows |
| `bullets` | `string[]` | Supporting explanation points |
| `actions` | `array` | Suggested next API calls relevant to the card |

---

### GET /ai/scheduling/jobs/:id/assist

Return a hybrid AI scheduling assist payload for one job.

This endpoint combines:

- backend readiness analysis
- solver preview / normalized scheduling problem
- earliest completion estimate
- delay-risk summary
- split suggestions per job step

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `string` | Job identifier |
| `readiness` | `object` | Same shape as `GET /scheduling/products/:id/readiness` |
| `solver_preview` | `object` | Same shape as `GET /scheduling/jobs/:id/solver-preview` |
| `estimated_completion` | `object` | Same shape as `GET /scheduling/jobs/:id/earliest-completion` |
| `delay_risk` | `object` | Same shape as `GET /predictive/high-risk-jobs` item |
| `split_suggestions` | `array` | Step-level split recommendations |
| `explanation` | `string[]` | Planner-readable explanation lines |

### GET /ai/scheduling/jobs/:id/delay-risk

Return a dedicated delay-risk evaluation for one job.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `string` | Job identifier |
| `product_id` | `string` | Product identifier |
| `risk_level` | `string` | `High` \| `Medium` \| `Low` |
| `risk_score` | `number` | Heuristic risk score |
| `issue` | `string` | Primary driver of the current risk |
| `delay_minutes` | `integer` | Current projected late minutes |
| `deadline` | `string` (RFC3339) | Job deadline |
| `earliest_ready_at` | `string` (RFC3339, optional) | Earliest readiness time if not immediately startable |
| `estimated_completion` | `string` (RFC3339, optional) | Current heuristic completion estimate |
| `reasons` | `string[]` | Explanation points behind the risk score |

### GET /ai/scheduling/jobs/:id/explanation

Return planner-readable explanation text and recommended actions for one job.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `string` | Job identifier |
| `summary` | `string` | High-level explanation summary |
| `key_points` | `string[]` | Main AI reasoning bullets |
| `recommended_actions` | `string[]` | Suggested planner next actions |
| `generated_at` | `string` (RFC3339) | Response generation timestamp |

### GET /ai/scheduling/jobs/:id/proposal

Return a draft heuristic slot proposal for a job.

This endpoint does not persist any slots. It is intended for planner review before manual acceptance or future solver automation.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `string` | Job identifier |
| `product_id` | `string` | Product identifier |
| `proposal_id` | `string` | Proposal ID when the proposal has been persisted |
| `version` | `integer` | Proposal version for the job |
| `status` | `string` | `draft`, `approved`, `rejected`, `applied`, or `stale` when persisted |
| `engine` | `string` | Engine that produced the proposal, such as `heuristic`, `preview-solver`, or `real-solver` |
| `engine_version` | `string` | Proposal engine version label |
| `objective_score` | `number` | Internal proposal score for comparison and rollout monitoring |
| `fallback_reason` | `string` | Reason the engine fell back to heuristic generation, if any |
| `snapshot_hash` | `string` | Stable input hash used for stale detection |
| `shadow_engine` | `string` | Shadow comparison engine when enabled |
| `shadow_objective_score` | `number` | Shadow comparison score when available |
| `rollout_state` | `string` | Rollout state used when the proposal was generated, such as `heuristic-only`, `shadow`, `candidate-default`, or `enforced-default` |
| `generated_at` | `string` (RFC3339) | Proposal generation timestamp |
| `feasible` | `boolean` | Whether the proposal completed without blocked steps |
| `earliest_start` | `string` (RFC3339) | Proposal start cursor |
| `estimated_completion` | `string` (RFC3339, optional) | Estimated completion of the draft plan |
| `summary` | `string[]` | Human-readable proposal summary lines |
| `blocked_reasons` | `string[]` | Reasons the proposal could not fully schedule all steps |
| `proposed_slots` | `array` | Proposed slot assignments |

Proposed slot fields:

- `job_step_id`
- `step_id`
- `step_name`
- `machine_id`
- `machine_name`
- `scheduled_start`
- `scheduled_end`
- `quantity_planned`
- `allocation_percent`
- `is_parallel`
- `batch_sequence`
- `estimated_duration_mins`
- `reasoning`

### POST /ai/scheduling/jobs/:id/apply-proposal

Deprecated compatibility endpoint for applying a job proposal in one step.

Current safety behavior:

- protected by planner/manager/admin role middleware
- disabled by default unless compatibility mode is explicitly enabled in backend feature flags
- only supports jobs without existing active slots
- reuses normal scheduling validation before slot creation
- does not silently overwrite an already scheduled job
- returns `409` when compatibility mode is disabled

Recommended replacement:

- `POST /ai/scheduling/jobs/:id/proposals`
- `POST /ai/scheduling/proposals/:id/approve`
- `POST /ai/scheduling/proposals/:id/apply`

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `string` | Job identifier |
| `proposal_id` | `string` | Persisted proposal that was applied |
| `applied_at` | `string` (RFC3339) | Apply timestamp |
| `applied_slot_count` | `integer` | Number of created slots |
| `created_slots` | `string[]` | Created slot IDs |
| `message` | `string` | Result summary |
| `idempotency_key` | `string` | Caller-supplied idempotency key when provided |
| `proposal` | `object` | The proposal that was applied |

### POST /ai/scheduling/jobs/:id/proposals

Generate and persist a first-class AI proposal record for a job.

This endpoint creates a reviewable proposal lifecycle resource with status, version, engine metadata, stale detection snapshot hash, and later production outcome tracking.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Response (201)** `data`:

Same shape as `GET /ai/scheduling/jobs/:id/proposal`, plus persisted lifecycle fields such as `proposal_id`, `version`, `status`, `engine`, `objective_score`, `snapshot_hash`, `rollout_state`, and persisted shadow/evaluation metadata.

### POST /ai/scheduling/batch-proposals

Generate and persist AI proposals for multiple jobs in one batch. Jobs are scheduled with shared machine state so that each subsequent job sees the tentative slots from earlier jobs. Sort order is configurable via `order_by` (default `product_deadline_fifo`). Requires `planner`, `manager`, or `admin` role.

**Request Body**

| Field | Type | Description |
|-------|------|-------------|
| `job_ids` | `string[]` | Explicit job IDs to schedule; if omitted and `scope` is set, use scope |
| `scope` | `string` | `"all_unscheduled"` = all jobs with status `planned` or `scheduled` and no active (planned/running) slots |
| `order_by` | `string` | Job ordering: `"edd"` (earliest due date), `"epo"` (priority then deadline), `"fifo"` (first in, first out), `"readiness"` (earliest ready first), `"material_priority"`, `"weighted_tardiness_material"`, or `"product_deadline_fifo"`. Default: `"product_deadline_fifo"` or `AI_BATCH_ORDER_BY` |

Either `job_ids` or `scope: "all_unscheduled"` must be provided.

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `proposals` | `array` | Generated `SchedulingProposal` objects (same shape as single-proposal endpoint) |
| `summary` | `object` | `{ "generated": number, "blocked": number, "skipped": number }` |

After generating batch proposals, call `POST /ai/scheduling/verify-overlaps` to check that no two slots use the same machine at the same time.

### POST /ai/scheduling/reschedule-all

Remove the current schedule and regenerate proposals for all planned/scheduled jobs. Cancels active slots and deletes proposals, then runs the same logic as batch-proposals with `scope: "all_unscheduled"`. Requires `planner`, `manager`, or `admin` role.

**Request Body (optional)**

| Field | Type | Description |
|-------|------|-------------|
| `order_by` | `string` | Job ordering: `"edd"`, `"epo"`, `"fifo"`, `"readiness"`, `"material_priority"`, `"weighted_tardiness_material"`, or `"product_deadline_fifo"`. Default: `"product_deadline_fifo"` |

**Response (200)** `data`:

Same as `batch-proposals`: `{ proposals, summary }`. Then call `POST /ai/scheduling/verify-overlaps` on the returned `proposal_ids`.

### POST /ai/scheduling/verify-overlaps

Verify that proposed slots do not overlap on the same machine. Use after `batch-proposals` or `reschedule-all` to ensure scheduling is valid.

**Request Body**

| Field | Type | Description |
|-------|------|-------------|
| `proposal_ids` | `string[]` | Proposal IDs to fetch from DB and verify |
| `proposals` | `array` | Inline proposals (e.g. `data.proposals` from batch-proposals response) |

Either `proposal_ids` or `proposals` must be provided. Each proposal must have `proposal_id`, `job_id`, and `proposed_slots` (with `job_step_id`, `machine_id`, `scheduled_start`, `scheduled_end`).

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `valid` | `boolean` | `true` if no overlaps |
| `total_slots` | `number` | Total slots checked |
| `overlap_count` | `number` | Number of overlapping pairs |
| `overlaps` | `array` | Details of each overlap: `machine_id`, `slot_a`, `slot_b`, `overlap_start`, `overlap_end` |

**Example** (verify batch response inline):

```json
POST /api/v1/ai/scheduling/verify-overlaps
{ "proposals": <data.proposals from batch-proposals response> }
```

### GET /ai/scheduling/jobs/:id/proposals

List persisted AI proposals for a job, newest first.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

### GET /ai/scheduling/proposals/:id

Get one persisted proposal by proposal ID.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – proposal ID |

### POST /ai/scheduling/proposals/:id/approve

Approve a persisted proposal for later application.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – proposal ID |

**Request Body**

| Field | Type |
|-------|------|
| `notes` | `string` |

### POST /ai/scheduling/proposals/:id/reject

Reject a persisted proposal and capture planner reason text.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – proposal ID |

**Request Body**

| Field | Type |
|-------|------|
| `reason` | `string` |

### POST /ai/scheduling/proposals/:id/apply

Apply an approved persisted proposal by proposal ID.

Behavior:

- returns `409` when the proposal is stale or already applied
- returns `422` when the proposal is not feasible, is still draft, or is otherwise not in an applicable state
- accepts `idempotency_key` for safe retries
- requires planner/manager/admin role middleware

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – proposal ID |

**Request Body**

| Field | Type |
|-------|------|
| `idempotency_key` | `string` |

**Response (200)** `data`:

Same shape as `POST /ai/scheduling/jobs/:id/apply-proposal`.

### GET /ai/scheduling/job-steps/:id/split-suggestion

Return a baseline split recommendation for a job step.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job step ID |

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `job_step_id` | `string` | Job step identifier |
| `recommended_splits` | `integer` | Suggested number of slot fragments |
| `allocation_percents` | `number[]` | Suggested percentage allocation per split |
| `is_parallel` | `boolean` | Whether the recommendation uses parallel execution |
| `reason` | `string` | Human-readable recommendation reason |

### GET /ai/scheduling/job-steps/:id/machine-ranking

Return ranked candidate machines for one job step in a requested time window.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job step ID |

**Query Parameters**

| Name | Type | Description |
|------|------|-------------|
| `start` | `string` | RFC3339 requested start time |
| `end` | `string` | RFC3339 requested end time |

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `job_step_id` | `string` | Job step identifier |
| `step_id` | `string` | Process step identifier |
| `step_name` | `string` | Process step name |
| `window_start` | `string` (RFC3339) | Ranking window start |
| `window_end` | `string` (RFC3339) | Ranking window end |
| `candidates` | `array` | Ranked machine options |

Candidate fields:

- `rank`
- `machine_id`
- `machine_name`
- `machine_type`
- `available`
- `available_from`
- `efficiency_factor`
- `capacity_per_hour`
- `estimated_duration_mins`
- `score`
- `reasons`
- `explanation`

### GET /ai/scheduling/bottleneck-forecast

Return AI-oriented bottleneck forecast entries for upcoming machine pressure.

**Query Parameters**

| Name | Type | Description |
|------|------|-------------|
| `days_ahead` | `integer` | Forecast horizon in days, default `7` |

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `days_ahead` | `integer` | Forecast horizon |
| `generated_at` | `string` (RFC3339) | Generation time |
| `entries` | `array` | Machine-level forecast entries |

Entry fields:

- `machine_id`
- `machine_name`
- `machine_type`
- `status`
- `upcoming_slots`
- `scheduled_minutes`
- `utilization_rate`
- `load_score`
- `at_risk`
- `reasons`

### GET /ai/scheduling/bottleneck-forecast

Return a short-horizon bottleneck forecast.

---

## AI Engine Reference

### Engine Types

| Engine | Description | How to Enable |
|--------|-------------|---------------|
| `heuristic` | Greedy earliest-start with parallel-split awareness. Lowest latency. | Default (`AI_ROLLOUT_STATE=heuristic-only`) |
| `preview-solver` | Sort-by-finish-time preview optimizer with parallel machine selection. | `AI_PROPOSAL_ENGINE=preview-solver` |
| `real-solver` | Production dispatching optimizer with local-search improvement. Uses efficiency factors, machine timelines, and a weighted objective (tardiness + makespan). | `AI_PROPOSAL_ENGINE=real-solver` or `AI_ROLLOUT_STATE=enforced-default` |

### Real Solver Algorithm (dispatch-ls-v1)

The `real-solver` engine (`dispatch-ls-v1`) runs a two-phase scheduling algorithm:

**Phase 1 – Greedy dispatch:**
For each job step in precedence order, the optimizer enumerates all feasible machine assignments (single machine and parallel combinations up to `max_parallel_machines`). Each assignment is scored using a weighted combination of:
- Time-to-deadline at projected finish (`earlinessScore`)
- Throughput (quantity / duration hours)
- Parallel bonus (steps scheduled across multiple machines get a small bonus to encourage load spreading)

The highest-scoring assignment is committed and machine free-at times are advanced.

**Phase 2 – Local search improvement:**
After the initial greedy schedule, the optimizer iterates over each step and tries alternative machine assignments. If any swap improves the overall objective score, it is accepted. This continues until no improving swap is found or the solver timeout fires (`AI_SOLVER_TIMEOUT_MS`).

**Objective score (0–1100):**

| Contribution | Formula |
|---|---|
| Base | 1000 |
| Tardiness penalty | `min(tardiness_minutes / 10, 500)` subtracted |
| Makespan penalty | `min(makespan_hours * 2, 200)` subtracted |
| Blocked step penalty | 300 per blocked step subtracted |
| Early finish bonus | `min(earlineess_hours * 5, 100)` added |

### Feature Flags

| Variable | Default | Description |
|---|---|---|
| `AI_PROPOSAL_ENGINE` | `heuristic` | Active primary engine: `heuristic`, `preview-solver`, `real-solver` |
| `AI_ROLLOUT_STATE` | `heuristic-only` | Rollout state that overrides engine selection: `heuristic-only`, `shadow`, `candidate-default`, `enforced-default` |
| `AI_SOLVER_SHADOW_MODE` | `false` | Run secondary engine in shadow and capture comparison evidence on every proposal |
| `AI_SOLVER_TIMEOUT_MS` | `2000` | Solver timeout in milliseconds |
| `EMAS_AUTO_MIGRATE` | `true` | Run GORM AutoMigrate on startup; set to `false` in production after applying reviewed SQL migrations |
| `AI_AUTH_REQUIRED` | `true` | Enforce `X-User-Role` header on proposal write endpoints |
| `AI_COMPAT_APPLY_ENABLED` | `false` | Enable deprecated job-based compatibility apply endpoint |
| `AI_PROPOSAL_APPLY_REQUIRES_APPROVAL` | `true` | Require `approved` status before `apply` |
| `AI_SOLVER_KPI_GATE` | `false` | Gate solver-default rollout behind persisted KPI thresholds |
| `AI_BATCH_ORDER_BY` | `product_deadline_fifo` | Default job ordering for batch proposals and reschedule-all: `edd`, `epo`, `fifo`, `readiness`, `material_priority`, `weighted_tardiness_material`, `product_deadline_fifo` |

### Rollout State Progression

```
heuristic-only  →  shadow  →  candidate-default  →  enforced-default
```

- `heuristic-only`: always uses heuristic engine; secondary engine may still run in shadow if `AI_SOLVER_SHADOW_MODE=true`
- `shadow`: primary engine is heuristic; secondary engine runs and is recorded but not used for scheduling
- `candidate-default`: promotes solver to primary if KPI gate passes; falls back to heuristic if gate fails
- `enforced-default`: always uses the configured engine regardless of KPI gate

---

### GET /ai/metrics

Return AI scheduling counters and persisted rollout KPI summaries for observability and rollout monitoring.

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `proposal_generated` | `integer` | Number of persisted proposals generated |
| `proposal_approved` | `integer` | Number of proposals approved |
| `proposal_rejected` | `integer` | Number of proposals rejected |
| `proposal_applied` | `integer` | Number of proposals applied |
| `proposal_stale` | `integer` | Number of stale detections |
| `proposal_apply_failures` | `integer` | Number of apply failures |
| `readonly_executions` | `integer` | Number of AI read-only command executions |
| `solver_executions` | `integer` | Number of solver-engine proposal generations |
| `heuristic_executions` | `integer` | Number of heuristic-engine proposal generations |
| `solver_fallbacks` | `integer` | Number of solver-to-heuristic fallbacks |
| `solver_shadow_samples` | `integer` | Number of persisted proposals that captured shadow-engine evidence |
| `acceptance_rate` | `number` | Applied proposals divided by generated proposals |
| `avg_estimate_deviation_mins` | `number` | Average planned-vs-actual completion deviation for proposals with recorded outcomes |
| `avg_scrap_qty` | `number` | Average recorded scrap quantity across proposals with outcomes |
| `rollout_state` | `string` | Active rollout state used by backend engine selection |
| `kpi_gate_passed` | `boolean` | Whether persisted KPI thresholds currently allow solver-default rollout when the KPI gate is enabled |

---

## Settings

### GET /settings

Get application settings.

**Response (200)** `data`:

| Field | Type |
|-------|------|
| `theme` | `string` |
| `language` | `string` |
| `notifications` | `boolean` |
| `ai_enabled` | `boolean` |
| `integrations` | `string[]` |

---

### PUT /settings

Update application settings.

**Request Body** (all optional)

| Field | Type |
|-------|------|
| `theme` | `string` |
| `language` | `string` |
| `notifications` | `boolean` |
| `ai_enabled` | `boolean` |

**Response (200)** `data`: same as GET /settings

---

## Reference / Lookup Data

Controlled vocabulary for dropdowns and form fields. See `API-ADDENDUM.md` for full spec.

### Machine Types

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /reference/machine-types | List all (sorted by name) |
| POST | /reference/machine-types | Create – `{ name, description? }` |
| PUT | /reference/machine-types/:id | Update – `{ name?, description? }` |
| DELETE | /reference/machine-types/:id | Delete (409 if in use by machines or process steps) |

**Response item** `{ id: number, name: string, description: string }`

---

### Product Types

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /reference/product-types | List all |
| POST | /reference/product-types | Create – `{ name }` (409 if duplicate) |
| DELETE | /reference/product-types/:id | Delete (409 if in use by products) |

**Response item** `{ id: number, name: string }`

---

### Factory Locations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /reference/locations | List all |
| POST | /reference/locations | Create – `{ zone, bay? }` |
| DELETE | /reference/locations/:id | Delete (409 if in use by machines) |

**Response item** `{ id: number, zone: string, bay: string | null, display: string }` — `display` is `zone` or `zone – bay`

---

### Storage Locations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /reference/storage-locations | List all |
| POST | /reference/storage-locations | Create – `{ name, type? }` (default type: `shelf`) |
| DELETE | /reference/storage-locations/:id | Delete (409 if in use by materials) |

**Response item** `{ id: number, name: string, type: string }` — `type`: `shelf` | `rack` | `cold` | `hazardous` | `floor` | `dock`

---

### Step Types

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /reference/step-types | List all |
| POST | /reference/step-types | Create – `{ name, default_machine_type? }` |
| DELETE | /reference/step-types/:id | Delete |

**Response item** `{ id: number, name: string, default_machine_type: string | null }`

---

## Product Scheduling Definition

### GET /products/:id/scheduling-definition

Return the canonical scheduling view for a product:

- `product`
- `formula`
- `ingredients`
- `process`
- `steps`
- `bom_items`

This endpoint is meant for frontend schedulers and AI preprocessing so they do not have to stitch formula and routing data manually.

---

## Inventory Extensions

### POST /inventory/product-stock

Create on-hand sub-product / WIP inventory.

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `product_id` | `string` | Yes | Product identifier |
| `quantity_on_hand` | `number` | Yes | Available stock quantity |
| `quantity_reserved` | `number` | No | Already reserved quantity |
| `status` | `string` | No | `available` \| `reserved` \| `blocked` |
| `storage_location` | `string` | No | Physical location |
| `available_from` | `string` | No | RFC3339 datetime |

### GET /inventory/product-stock

List seeded and user-created product inventory records.

### POST /inventory/reservations

Create a material reservation.

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `material_id` | `string` | Yes | Reserved material |
| `job_id` | `string` | No | Owning job |
| `job_step_id` | `string` | No | Owning job step |
| `reserved_qty` | `number` | Yes | Reserved quantity |
| `needed_at` | `string` | No | RFC3339 datetime |

### GET /inventory/reservations

Query parameters:

- `material_id`
- `status`

---

## Scheduling APIs

### GET /scheduling/products/:id/explosion

Preview recursive material and sub-product demand for a product. Query parameter:

- `quantity` (default `1`)

### GET /scheduling/products/:id/readiness

Return reservation-aware material readiness and sub-product availability. Query parameter:

- `quantity` (default `1`)

### GET /scheduling/steps/:id/candidate-machines

Return capable machines ranked by availability and efficiency.

**Query Parameters**

| Name | Type | Description |
|------|------|-------------|
| `start` | `string` | RFC3339 requested start |
| `end` | `string` | RFC3339 requested end |

### POST /scheduling/slots/validate

Validate one candidate slot before writing it.

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `job_step_id` | `string` | Yes | Job step identifier |
| `machine_id` | `string` | Yes | Candidate machine |
| `scheduled_start` | `string` | Yes | RFC3339 start |
| `scheduled_end` | `string` | Yes | RFC3339 end |
| `quantity` | `integer` | Yes | Quantity planned in the slot |
| `exclude_slot_id` | `string` | No | Existing slot ID when validating updates |

The response includes `valid` and `reasons[]`.

### GET /scheduling/jobs/:id/earliest-completion

Estimate the earliest completion time using current readiness, machine capability, and slot occupancy.

### GET /scheduling/jobs/:id/solver-preview

Return a solver-ready preview of the scheduling problem for one job.

**Path Parameters**

| Name | Type |
|------|------|
| `id` | `string` – job ID |

**Response (200)** `data`:

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `string` | Job identifier |
| `product_id` | `string` | Product identifier |
| `quantity_total` | `integer` | Job quantity |
| `priority` | `string` | Job priority |
| `deadline` | `string` (RFC3339) | Job deadline |
| `can_start_now` | `boolean` | Whether readiness allows immediate start |
| `earliest_ready_at` | `string` (RFC3339, optional) | Earliest feasible material/sub-product ready time |
| `estimated_completion` | `string` (RFC3339, optional) | Current heuristic completion estimate |
| `objectives` | `string[]` | Optimization objective hints |
| `constraints` | `string[]` | Hard constraints that solver output must satisfy |
| `steps` | `array` | Step-level solver input |

### GET /scheduling/training-dataset

Export scheduler-ready rows with real `step_id` lineage and production-log-derived quantities. Synthetic / missing-step rows are excluded.

The dataset now includes:

- readiness context
- shortage counts
- nesting depth
- machine capacity / efficiency
- maintenance proximity
- calendar presence
- completion ratio and delay minutes

---

## Use Case Coverage

| Section | Use Case | API |
|---------|----------|-----|
| **Job** | UC-J01 Create | POST /jobs |
| | UC-J02 Create via NLP | POST /ai/command → POST /jobs |
| | UC-J03 List | GET /jobs |
| | UC-J04 Details | GET /jobs/:id, /jobs/:id/steps, /jobs/:id/slots |
| | UC-J05 Update | PUT /jobs/:id, PUT /slots/:id |
| | UC-J06 Update via NLP | POST /ai/command → PUT /slots/:id |
| | UC-J07 Delete/cancel | DELETE /jobs/:id, DELETE /slots/:id |
| | UC-J08 Duplicate | POST /jobs/:id/duplicate |
| **Job Step** | UC-JS01 Create from routing | POST /job-steps |
| | UC-JS02 Assign machines | PUT /slots/:id, POST /job-steps/split |
| | UC-JS03 Split step | POST /job-steps/split |
| | UC-JS04 Update slot | PUT /slots/:id |
| | UC-JS05 View slot | GET /slots/:id |
| **Machine** | UC-M01 Create | POST /machines |
| | UC-M02 Capabilities | POST /machines/:id/capabilities |
| | UC-M03 Downtime | POST /machines/downtime |
| | UC-M04 Maintenance alerts | GET /machines/maintenance-alerts |
| **Product** | UC-P01 Link formula/BOM | PUT /products/:id/bom |
| **Inventory** | UC-S01 Consume | POST /inventory/consume |
| | UC-S02 Consume via NLP | POST /ai/command → POST /inventory/consume |
| **Production** | UC-PL01 Log | POST /production-logs |
| | UC-PL02 Quality | POST /quality/inspections |
