# API: Materials per Process Step (BOM & Process Routing)

Clear API reference for the **"Materials (none)"** section in the BOM & Process Routing modal. Use these endpoints to display and edit materials for each production step.

**Base URL:** `/api/v1` (e.g. `http://localhost:8080/api/v1`)

---

## Quick reference — How to use (frontend)

### List materials (BOM & Process Routing)

```
GET /api/v1/process-steps/STP-P001-1/materials?role=all
```

| `role` | Use |
|--------|-----|
| `input` | Inputs only (default) |
| `output` | Outputs only |
| `all` | Inputs + outputs — **use this in BOM modal** |

### Add material to a step

```
POST /api/v1/process-steps/STP-P001-1/materials
Content-Type: application/json

{
  "material_id": "MAT-001",
  "product_id": "",
  "role": "input",
  "quantity_per_unit": 2.5,
  "unit": "kg"
}
```

- Use **either** `material_id` (raw material) **or** `product_id` (sub-assembly), not both.
- `role`: `"input"` or `"output"`.

### Remove material from a step

```
DELETE /api/v1/process-steps/STP-P001-1/materials/PSM-P001-1-MAT001
```

- `:id` is the `id` from the GET response (e.g. `PSM-P001-1-MAT001`).

---

## Data flow: how to get `step_id`

The BOM modal shows **Process Routing** for a product (e.g. Valve Body Assembly). Each step needs a `step_id` to fetch materials.

```
Product (P-001)  →  Process (PRC-001)  →  Steps  →  Materials per step
```

| Step | API | Result |
|------|-----|--------|
| 1 | `GET /products/P-001/process` | `{ process_id: "PRC-001", process_name: "Valve Body Standard Routing" }` |
| 2 | `GET /processes/PRC-001/steps` | Array of steps, each with `step_id` |
| 3 | `GET /process-steps/{step_id}/materials` | Materials for that step |

**Example:** Step 1 "CNC Rough Milling" has `step_id: "STP-P001-1"`. Call `GET /process-steps/STP-P001-1/materials`.

---

## 1. List materials for a step

**Request**
```
GET /api/v1/process-steps/:step_id/materials?role=all
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `step_id` | path | required | Process step ID (e.g. `STP-P001-1`) |
| `role` | query | `input` | `input` = inputs only, `output` = outputs only, `all` = both |

**Use `role=all`** in the BOM & Process Routing modal to show all materials (inputs + outputs).

**Example request**
```http
GET /api/v1/process-steps/STP-P001-1/materials?role=all
```

**Success response (200)**
```json
{
  "success": true,
  "data": [
    {
      "id": "PSM-P001-1-MAT001",
      "material_id": "MAT-001",
      "product_id": "",
      "role": "input",
      "quantity_per_unit": 2.5,
      "unit": "kg",
      "material_name": "Steel Sheet"
    },
    {
      "id": "PSM-P001-1-MAT002",
      "material_id": "MAT-002",
      "product_id": "",
      "role": "input",
      "quantity_per_unit": 0.08,
      "unit": "kg",
      "material_name": "Alloy Additive"
    }
  ]
}
```

**Display format:**  
`MAT-001 (2.5 kg), MAT-002 (0.08 kg)` — or use `material_name` when available.

If `data` is empty, show **"Materials (none)"**.

**Error responses**
- `400` — Missing `step_id`
- `500` — Server error

---

## 2. Add material to a step

**Request**
```
POST /api/v1/process-steps/:step_id/materials
Content-Type: application/json
```

**Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `material_id` | string | one of these | Raw material ID (e.g. `MAT-001`) |
| `product_id` | string | one of these | Sub-product ID (e.g. `P-007`) |
| `role` | string | yes | `input` or `output` |
| `quantity_per_unit` | number | yes | Quantity per 1 unit produced (must be > 0) |
| `unit` | string | no | Unit (e.g. `kg`, `L`, `pcs`, `set`) |

**Rule:** Send exactly one of `material_id` or `product_id`, not both.

**Example: add raw material**
```http
POST /api/v1/process-steps/STP-P001-1/materials
Content-Type: application/json

{
  "material_id": "MAT-001",
  "product_id": "",
  "role": "input",
  "quantity_per_unit": 2.5,
  "unit": "kg"
}
```

**Example: add sub-product**
```http
POST /api/v1/process-steps/STP-P001-5/materials
Content-Type: application/json

{
  "material_id": "",
  "product_id": "P-008",
  "role": "input",
  "quantity_per_unit": 1,
  "unit": "pcs"
}
```

**Success response (201)**
```json
{
  "success": true,
  "data": {
    "ID": "PSM-abc123",
    "step_id": "STP-P001-1",
    "material_id": "MAT-001",
    "role": "input",
    "quantity_per_unit": 2.5,
    "unit": "kg"
  }
}
```

**Error responses**
- `400` — Validation error (e.g. both material_id and product_id set, or neither; invalid role; quantity ≤ 0)
- `404` — Step not found
- `500` — Server error

---

## 3. Remove material from a step

**Request**
```
DELETE /api/v1/process-steps/:step_id/materials/:id
```

| Parameter | Description |
|-----------|-------------|
| `step_id` | Process step ID |
| `id` | Material record ID from the GET response (e.g. `PSM-P001-1-MAT001`) |

**Example request**
```http
DELETE /api/v1/process-steps/STP-P001-1/materials/PSM-P001-1-MAT001
```

**Success response (200)**
```json
{
  "success": true
}
```

**Error responses**
- `400` — Missing `step_id` or `id`
- `404` — Material record not found, or it belongs to a different step
- `500` — Server error

---

## Quick reference

| Action | Method | Path |
|--------|--------|------|
| List materials | GET | `/api/v1/process-steps/:step_id/materials?role=all` |
| Add material | POST | `/api/v1/process-steps/:step_id/materials` |
| Remove material | DELETE | `/api/v1/process-steps/:step_id/materials/:id` |

---

## Frontend integration checklist (BOM & Process Routing)

1. **Get steps:** `GET /processes/{process_id}/steps` — each step has `step_id`.
2. **For each step card:** Call `GET /process-steps/{step_id}/materials?role=all`.
3. **Display:** If `data.length > 0`, show e.g. `MAT-001 (2.5 kg), P-007 (1 set)`. Else show "Materials (none)".
4. **Add:** Add "Add material" control; on submit → `POST /process-steps/{step_id}/materials`.
5. **Remove:** Add delete icon per material; on click → `DELETE /process-steps/{step_id}/materials/{id}`.
6. **Refresh:** After add/delete, re-fetch materials for that step.

---

## Reference data

- **Materials list:** `GET /api/v1/inventory/materials` — for the "Add material" dropdown (use `material_id`, `material_name`).
- **Products list:** `GET /api/v1/products` — for sub-products in "Add material" (use `product_id`, `product_name`).

---

## Troubleshooting: "Materials (none)" still showing

### 1. Use the correct property: `step_id`

`GET /processes/:id/steps` returns steps with **snake_case** keys. Use `step.step_id`:

```javascript
// Correct
steps.forEach(step => {
  getStepMaterials(step.step_id, 'all')  // step_id = "STP-P001-1", "STP-P001-2", etc.
})

// Wrong — will pass undefined
getStepMaterials(step.StepID, 'all')   // PascalCase not returned
getStepMaterials(step.stepId, 'all')   // camelCase not returned
```

### 2. Do not use step index or sequence

- `step_id` is a string like `"STP-P001-1"`, not `1` or `"1"`.
- Do not use `step.step_sequence` or array index as the step_id.

### 3. Ensure you have the process before fetching steps

```
GET /products/P-001/process  →  process_id: "PRC-001"
GET /processes/PRC-001/steps →  array of steps, each with step_id
```

### 4. Re-run seed if the DB was created before materials were seeded

```bash
# Reset and re-seed
mysql ... < scripts/reset_seed.sql
go run ./cmd/seed
```

### 5. Verify the API directly

```bash
# List steps (get step_id from response)
curl http://localhost:8080/api/v1/processes/PRC-001/steps

# Get materials for step 1
curl "http://localhost:8080/api/v1/process-steps/STP-P001-1/materials?role=all"
```

If the second call returns `{"success":true,"data":[...]}` with items, the backend is correct. If the frontend still shows "(none)", the issue is which `step_id` is being passed.
