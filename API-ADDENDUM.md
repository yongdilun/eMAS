# eMAS API Addendum — Reference / Lookup Data

Base URL: `http://localhost:8080/api/v1`

> **Purpose:** This document specifies new backend endpoints required to manage
> all controlled-vocabulary fields (types, categories, locations, step templates)
> as database records rather than hard-coded frontend lists.
>
> **Priority:** These endpoints are blocking for the following forms:
> - Add / Edit Product → Product Type
> - Add / Edit Machine → Machine Type, Factory Location
> - Add / Edit Inventory Item → Storage Location
> - BOM & Process Routing → Step Type, Machine Type Required
>
> **All responses follow the standard eMAS wrapper:**
> ```json
> { "success": true, "data": <payload> }
> { "success": false, "error": "message" }
> ```

---

## 1. Machine Types  `/reference/machine-types`

Stores every machine category recognised by the factory. Used when:
- registering a new machine (`machine_type` field in `POST /machines`), and
- defining which machine category is required for a BOM process step
  (`machine_type_required` in `POST /processes/:id/steps`).

### GET /reference/machine-types

Return all machine types in alphabetical order.

**Response (200)**

```json
{
  "success": true,
  "data": [
    { "id": 1, "name": "CNC Mill",         "description": "3-axis/5-axis CNC milling centres" },
    { "id": 2, "name": "CNC Lathe",        "description": "Turning centres" },
    { "id": 3, "name": "Welding Robot",    "description": "Automated arc / MIG / TIG welders" },
    { "id": 4, "name": "Coating Station",  "description": "Spray / powder coating booths" }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `integer` | Surrogate key |
| `name` | `string` | Display name (unique) |
| `description` | `string` | Optional clarification |

---

### POST /reference/machine-types

Create a new machine type.

**Request Body**

| Field | Type | Required |
|-------|------|----------|
| `name` | `string` | Yes — must be unique |
| `description` | `string` | No |

**Response (201)** `data`: the created machine-type object.

**Errors**

| Code | Condition |
|------|-----------|
| 409 | `name` already exists |
| 422 | `name` is blank |

---

### PUT /reference/machine-types/:id

Update name or description of an existing machine type.

**Path Parameters** `id`: integer

**Request Body** (all optional)

| Field | Type |
|-------|------|
| `name` | `string` |
| `description` | `string` |

**Response (200)** `data`: updated object

---

### DELETE /reference/machine-types/:id

Remove a machine type.

> **Constraint:** reject with `409` if any `machines.machine_type` or
> `process_steps.machine_type_required` still references this name.

**Response (200)** `success: true`, no `data`

---

---

## 2. Product Categories  `/reference/product-types`

Stores the controlled vocabulary for `products.product_type`.  
Used in `POST /products` and `PUT /products/:id`.

### GET /reference/product-types

**Response (200)**

```json
{
  "success": true,
  "data": [
    { "id": 1, "name": "Hydraulic Components" },
    { "id": 2, "name": "Mechanical Parts" },
    { "id": 3, "name": "Electronic Components" },
    { "id": 4, "name": "Assembly / Sub-assembly" },
    { "id": 5, "name": "Raw Material" },
    { "id": 6, "name": "Finished Goods" },
    { "id": 7, "name": "Consumables" },
    { "id": 8, "name": "Chemical / Fluid" },
    { "id": 9, "name": "Tooling & Fixtures" },
    { "id": 10, "name": "Packaging Material" }
  ]
}
```

| Field | Type |
|-------|------|
| `id` | `integer` |
| `name` | `string` (unique) |

---

### POST /reference/product-types

| Field | Type | Required |
|-------|------|----------|
| `name` | `string` | Yes |

**Response (201)** `data`: created object.  
**409** if `name` already exists.

---

### DELETE /reference/product-types/:id

> **Constraint:** reject with `409` if any product still references this type.

---

---

## 3. Factory Floor Locations  `/reference/locations`

Stores physical zones/bays where machines are installed.  
Used in `machines.location`.

### GET /reference/locations

**Response (200)**

```json
{
  "success": true,
  "data": [
    { "id": 1, "zone": "Floor A", "bay": "Bay 1", "display": "Floor A – Bay 1" },
    { "id": 2, "zone": "Floor A", "bay": "Bay 2", "display": "Floor A – Bay 2" },
    { "id": 5, "zone": "Floor B", "bay": "Bay 1", "display": "Floor B – Bay 1" },
    { "id": 10, "zone": "Maintenance Bay", "bay": null, "display": "Maintenance Bay" },
    { "id": 11, "zone": "Quality Lab",     "bay": null, "display": "Quality Lab" }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `integer` | Surrogate key |
| `zone` | `string` | Top-level area (Floor A, Maintenance Bay …) |
| `bay` | `string \| null` | Sub-bay within zone, null if not applicable |
| `display` | `string` | Pre-formatted label for dropdowns |

---

### POST /reference/locations

| Field | Type | Required |
|-------|------|----------|
| `zone` | `string` | Yes |
| `bay` | `string` | No |

**Response (201)** `data`: created location object.

---

### DELETE /reference/locations/:id

> **Constraint:** reject with `409` if any machine still references this location.

---

---

## 4. Storage Locations  `/reference/storage-locations`

Stores warehouse racks, shelves, and zones where inventory is kept.  
Used in `inventory/materials.storage_location`.

### GET /reference/storage-locations

**Response (200)**

```json
{
  "success": true,
  "data": [
    { "id": 1,  "name": "Warehouse A – Shelf 1",  "type": "shelf" },
    { "id": 2,  "name": "Warehouse A – Shelf 2",  "type": "shelf" },
    { "id": 5,  "name": "Warehouse B – Shelf 1",  "type": "shelf" },
    { "id": 10, "name": "Rack-A1",               "type": "rack" },
    { "id": 15, "name": "Cold Storage",          "type": "cold" },
    { "id": 16, "name": "Hazardous Storage",     "type": "hazardous" }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `integer` | Surrogate key |
| `name` | `string` (unique) | Display label |
| `type` | `string` | `shelf` \| `rack` \| `cold` \| `hazardous` \| `floor` \| `dock` |

---

### POST /reference/storage-locations

| Field | Type | Required |
|-------|------|----------|
| `name` | `string` | Yes — unique |
| `type` | `string` | No (defaults to `shelf`) |

**Response (201)** `data`: created object.  
**409** if `name` already exists.

---

### DELETE /reference/storage-locations/:id

> **Constraint:** reject with `409` if any material still references this location.

---

---

## 5. Process Step Types  `/reference/step-types`

Stores named templates for production steps.  
Used in `POST /processes/:id/steps` (`step_name` field).  
Allows planners to pick a standard step name rather than typing free text.

### GET /reference/step-types

**Response (200)**

```json
{
  "success": true,
  "data": [
    { "id": 1,  "name": "Raw Material Preparation",  "default_machine_type": null },
    { "id": 2,  "name": "CNC Machining",             "default_machine_type": "CNC Mill" },
    { "id": 3,  "name": "Turning / Lathing",         "default_machine_type": "CNC Lathe" },
    { "id": 4,  "name": "Milling",                   "default_machine_type": "Milling Machine" },
    { "id": 5,  "name": "Drilling",                  "default_machine_type": "Drilling Machine" },
    { "id": 6,  "name": "Grinding / Polishing",      "default_machine_type": "Grinding Machine" },
    { "id": 7,  "name": "Heat Treatment",            "default_machine_type": "Heat Treatment Unit" },
    { "id": 8,  "name": "Surface Coating",           "default_machine_type": "Coating Station" },
    { "id": 9,  "name": "Welding",                   "default_machine_type": "Welding Robot" },
    { "id": 10, "name": "Assembly",                  "default_machine_type": "Assembly Station" },
    { "id": 11, "name": "Sub-Assembly",              "default_machine_type": "Assembly Station" },
    { "id": 12, "name": "Quality Inspection",        "default_machine_type": "Quality Control Station" },
    { "id": 13, "name": "Packaging",                 "default_machine_type": null }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `integer` | Surrogate key |
| `name` | `string` (unique) | Step template name |
| `default_machine_type` | `string \| null` | Suggested machine type for auto-fill |

> **UX bonus:** When a user selects a step type whose `default_machine_type` is not
> null, the frontend **auto-fills** the Machine Type Required field to that value
> (user can override it). This reduces data entry errors.

---

### POST /reference/step-types

| Field | Type | Required |
|-------|------|----------|
| `name` | `string` | Yes — unique |
| `default_machine_type` | `string` | No |

**Response (201)** `data`: created object.

---

### DELETE /reference/step-types/:id

---

---

## Summary Table

| Endpoint prefix | Used by form field | Blocks which form |
|---|---|---|
| `GET /reference/machine-types` | `machine_type` (AddMachineModal) | Add / Edit Machine |
| `GET /reference/machine-types` | `machine_type_required` (BomModal step) | BOM & Process Routing |
| `GET /reference/product-types` | `product_type` (ProductModal) | Add / Edit Product |
| `GET /reference/locations` | `location` (AddMachineModal) | Add / Edit Machine |
| `GET /reference/storage-locations` | `storage_location` (AddItemModal) | Add / Edit Inventory Item |
| `GET /reference/step-types` | `step_name` (BomModal step) | BOM & Process Routing |

## Suggested DB Schema (PostgreSQL)

```sql
-- Machine types
CREATE TABLE reference_machine_types (
  id          SERIAL PRIMARY KEY,
  name        VARCHAR(100) NOT NULL UNIQUE,
  description TEXT
);

-- Product categories
CREATE TABLE reference_product_types (
  id   SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL UNIQUE
);

-- Factory floor locations
CREATE TABLE reference_locations (
  id      SERIAL PRIMARY KEY,
  zone    VARCHAR(100) NOT NULL,
  bay     VARCHAR(50),
  display VARCHAR(150) GENERATED ALWAYS AS (
    CASE WHEN bay IS NULL THEN zone ELSE zone || ' – ' || bay END
  ) STORED,
  UNIQUE(zone, bay)
);

-- Warehouse / storage locations
CREATE TABLE reference_storage_locations (
  id   SERIAL PRIMARY KEY,
  name VARCHAR(150) NOT NULL UNIQUE,
  type VARCHAR(50) DEFAULT 'shelf'
);

-- Process step type templates
CREATE TABLE reference_step_types (
  id                   SERIAL PRIMARY KEY,
  name                 VARCHAR(100) NOT NULL UNIQUE,
  default_machine_type VARCHAR(100) REFERENCES reference_machine_types(name) ON DELETE SET NULL
);
```

## Seed Data (initial records)

```sql
INSERT INTO reference_machine_types (name, description) VALUES
  ('CNC Mill',                   '3-axis / 5-axis milling centres'),
  ('CNC Lathe',                  'Turning centres'),
  ('3D Printer',                 'FDM / SLA additive manufacturing'),
  ('Welding Robot',              'Automated arc / MIG / TIG welders'),
  ('Stamping Press',             'Metal forming press'),
  ('Hydraulic Press',            'Hydraulic forming / punching press'),
  ('Laser Cutter',               'CO₂ / fibre laser cutting'),
  ('Laser Welder',               'Precision laser welding'),
  ('Assembly Robot',             'Pick-and-place / SCARA robot'),
  ('Assembly Station',           'Manual or semi-automated assembly bench'),
  ('Coating Station',            'Spray / powder coating booth'),
  ('Painting Station',           'Automated painting line'),
  ('Heat Treatment Unit',        'Furnace / oven / annealing unit'),
  ('Quality Control Station',    'CMM / vision inspection station'),
  ('Conveyor System',            'Material transport conveyor'),
  ('Grinding Machine',           'Surface / cylindrical grinder'),
  ('Drilling Machine',           'Radial / column drill press'),
  ('Milling Machine',            'Conventional milling machine');

INSERT INTO reference_product_types (name) VALUES
  ('Hydraulic Components'),
  ('Mechanical Parts'),
  ('Electronic Components'),
  ('Assembly / Sub-assembly'),
  ('Raw Material'),
  ('Finished Goods'),
  ('Consumables'),
  ('Chemical / Fluid'),
  ('Tooling & Fixtures'),
  ('Packaging Material');

INSERT INTO reference_locations (zone, bay) VALUES
  ('Floor A', 'Bay 1'), ('Floor A', 'Bay 2'), ('Floor A', 'Bay 3'),
  ('Floor B', 'Bay 1'), ('Floor B', 'Bay 2'), ('Floor B', 'Bay 3'),
  ('Floor C', 'Bay 1'), ('Floor C', 'Bay 2'),
  ('Maintenance Bay', NULL), ('Quality Lab', NULL),
  ('Paint Shop', NULL), ('Warehouse Area', NULL),
  ('Loading Dock', NULL), ('Clean Room', NULL);

INSERT INTO reference_storage_locations (name, type) VALUES
  ('Warehouse A – Shelf 1', 'shelf'), ('Warehouse A – Shelf 2', 'shelf'),
  ('Warehouse A – Shelf 3', 'shelf'), ('Warehouse B – Shelf 1', 'shelf'),
  ('Warehouse B – Shelf 2', 'shelf'),
  ('Rack-A1', 'rack'), ('Rack-A2', 'rack'), ('Rack-A3', 'rack'),
  ('Rack-B1', 'rack'), ('Rack-B2', 'rack'), ('Rack-B3', 'rack'),
  ('Cold Storage', 'cold'), ('Hazardous Storage', 'hazardous'),
  ('Floor Storage', 'floor'), ('Receiving Dock', 'dock'),
  ('Shipping Dock', 'dock');

INSERT INTO reference_step_types (name, default_machine_type) VALUES
  ('Raw Material Preparation', NULL),
  ('CNC Machining',            'CNC Mill'),
  ('Turning / Lathing',        'CNC Lathe'),
  ('Milling',                  'Milling Machine'),
  ('Drilling',                 'Drilling Machine'),
  ('Grinding / Polishing',     'Grinding Machine'),
  ('Heat Treatment',           'Heat Treatment Unit'),
  ('Surface Coating',          'Coating Station'),
  ('Welding',                  'Welding Robot'),
  ('Assembly',                 'Assembly Station'),
  ('Sub-Assembly',             'Assembly Station'),
  ('Quality Inspection',       'Quality Control Station'),
  ('Packaging',                NULL);
```
