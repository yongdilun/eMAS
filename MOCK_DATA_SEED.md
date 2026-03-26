# eMAS — Realistic Mock Data Seed

All requests target `http://localhost:8080/api/v1`.  
Run them in order (machines → products → processes → formulas → jobs → inventory → logs).

---

## 1. Machines (8 machines)

```json
POST /machines
{ "machine_id": "M-CNC-01", "machine_name": "CNC Mill 01", "machine_type": "CNC Milling", "status": "Running", "max_capacity": 200, "maintenance_interval_days": 30, "last_maintenance_date": "2026-01-15", "location": "Bay A-1" }

POST /machines
{ "machine_id": "M-CNC-02", "machine_name": "CNC Mill 02", "machine_type": "CNC Milling", "status": "Running", "max_capacity": 200, "maintenance_interval_days": 30, "last_maintenance_date": "2026-01-20", "location": "Bay A-2" }

POST /machines
{ "machine_id": "M-LTH-01", "machine_name": "Lathe 01", "machine_type": "Turning", "status": "Running", "max_capacity": 150, "maintenance_interval_days": 45, "last_maintenance_date": "2026-01-10", "location": "Bay B-1" }

POST /machines
{ "machine_id": "M-LTH-02", "machine_name": "Lathe 02", "machine_type": "Turning", "status": "Idle", "max_capacity": 150, "maintenance_interval_days": 45, "last_maintenance_date": "2025-12-28", "location": "Bay B-2" }

POST /machines
{ "machine_id": "M-PRS-01", "machine_name": "Hydraulic Press 01", "machine_type": "Pressing", "status": "Running", "max_capacity": 300, "maintenance_interval_days": 60, "last_maintenance_date": "2025-12-01", "location": "Bay C-1" }

POST /machines
{ "machine_id": "M-CTG-01", "machine_name": "Coating Station 01", "machine_type": "Surface Coating", "status": "Maintenance", "max_capacity": 100, "maintenance_interval_days": 14, "last_maintenance_date": "2026-02-01", "location": "Bay D-1" }

POST /machines
{ "machine_id": "M-ASM-01", "machine_name": "Assembly Station 01", "machine_type": "Assembly", "status": "Running", "max_capacity": 250, "maintenance_interval_days": 90, "last_maintenance_date": "2026-01-05", "location": "Bay E-1" }

POST /machines
{ "machine_id": "M-QC-01", "machine_name": "Quality Control Station", "machine_type": "Inspection", "status": "Running", "max_capacity": 500, "maintenance_interval_days": 180, "last_maintenance_date": "2025-11-01", "location": "Bay F-1" }
```

---

## 2. Machine Capabilities

```json
POST /machines/M-CNC-01/capabilities
{ "capability": "High-precision milling", "tolerance_mm": 0.01 }

POST /machines/M-CNC-02/capabilities
{ "capability": "High-precision milling", "tolerance_mm": 0.01 }

POST /machines/M-LTH-01/capabilities
{ "capability": "Cylindrical turning", "max_diameter_mm": 300 }

POST /machines/M-LTH-02/capabilities
{ "capability": "Cylindrical turning", "max_diameter_mm": 300 }

POST /machines/M-PRS-01/capabilities
{ "capability": "Cold pressing up to 500T", "max_force_ton": 500 }

POST /machines/M-CTG-01/capabilities
{ "capability": "Epoxy and powder coating", "max_temp_c": 200 }
```

---

## 3. Products (6 products)

```json
POST /products
{ "product_id": "P-001", "product_name": "Valve Body Assembly", "category": "Hydraulic Components", "unit": "pcs", "description": "High-pressure valve body used in industrial hydraulic systems" }

POST /products
{ "product_id": "P-002", "product_name": "Precision Gear Set", "category": "Power Transmission", "unit": "set", "description": "Hardened steel gear set for industrial gearboxes, tolerance ±0.005mm" }

POST /products
{ "product_id": "P-003", "product_name": "Hydraulic Cylinder Rod", "category": "Hydraulic Components", "unit": "pcs", "description": "Chrome-plated cylinder rod, 50mm diameter, 400mm stroke" }

POST /products
{ "product_id": "P-004", "product_name": "Motor Housing", "category": "Electrical Enclosures", "unit": "pcs", "description": "Die-cast aluminium housing for 15kW induction motors" }

POST /products
{ "product_id": "P-005", "product_name": "Control Bracket", "category": "Structural Parts", "unit": "pcs", "description": "Mounting bracket for control panel assemblies, powder-coated" }

POST /products
{ "product_id": "P-006", "product_name": "Pump Casing", "category": "Fluid Handling", "unit": "pcs", "description": "Cast iron pump casing for centrifugal pumps, 3-inch port" }
```

---

## 4. Processes (Routing per product)

### P-001 Valve Body Assembly
```json
POST /processes
{ "process_id": "PRC-001", "product_id": "P-001", "process_name": "Valve Body Standard Routing" }

POST /processes/PRC-001/steps
{ "step_name": "CNC Rough Milling",     "machine_type_required": "CNC Milling",     "sequence": 1, "duration_mins": 90  }
POST /processes/PRC-001/steps
{ "step_name": "CNC Finish Milling",    "machine_type_required": "CNC Milling",     "sequence": 2, "duration_mins": 60  }
POST /processes/PRC-001/steps
{ "step_name": "Turning – Bore",        "machine_type_required": "Turning",          "sequence": 3, "duration_mins": 45  }
POST /processes/PRC-001/steps
{ "step_name": "Surface Coating",       "machine_type_required": "Surface Coating",  "sequence": 4, "duration_mins": 120 }
POST /processes/PRC-001/steps
{ "step_name": "Final Assembly & Test", "machine_type_required": "Assembly",         "sequence": 5, "duration_mins": 60  }
```

### P-002 Precision Gear Set
```json
POST /processes
{ "process_id": "PRC-002", "product_id": "P-002", "process_name": "Gear Set Precision Routing" }

POST /processes/PRC-002/steps
{ "step_name": "Gear Blank Turning",    "machine_type_required": "Turning",      "sequence": 1, "duration_mins": 75 }
POST /processes/PRC-002/steps
{ "step_name": "Hobbing / CNC Mill",    "machine_type_required": "CNC Milling",  "sequence": 2, "duration_mins": 120 }
POST /processes/PRC-002/steps
{ "step_name": "Gear Inspection",       "machine_type_required": "Inspection",   "sequence": 3, "duration_mins": 30 }
```

### P-003 Hydraulic Cylinder Rod
```json
POST /processes
{ "process_id": "PRC-003", "product_id": "P-003", "process_name": "Cylinder Rod Routing" }

POST /processes/PRC-003/steps
{ "step_name": "Bar Turning",           "machine_type_required": "Turning",          "sequence": 1, "duration_mins": 50  }
POST /processes/PRC-003/steps
{ "step_name": "Chrome Plating",        "machine_type_required": "Surface Coating",  "sequence": 2, "duration_mins": 150 }
POST /processes/PRC-003/steps
{ "step_name": "Final Inspection",      "machine_type_required": "Inspection",       "sequence": 3, "duration_mins": 20  }
```

### P-004 Motor Housing
```json
POST /processes
{ "process_id": "PRC-004", "product_id": "P-004", "process_name": "Motor Housing Routing" }

POST /processes/PRC-004/steps
{ "step_name": "Rough Boring",          "machine_type_required": "CNC Milling",  "sequence": 1, "duration_mins": 60 }
POST /processes/PRC-004/steps
{ "step_name": "Drilling & Tapping",    "machine_type_required": "CNC Milling",  "sequence": 2, "duration_mins": 45 }
POST /processes/PRC-004/steps
{ "step_name": "Powder Coating",        "machine_type_required": "Surface Coating", "sequence": 3, "duration_mins": 90 }
POST /processes/PRC-004/steps
{ "step_name": "Assembly & QC",         "machine_type_required": "Assembly",     "sequence": 4, "duration_mins": 40 }
```

---

## 5. Formulas / BOM

### P-001 Valve Body Assembly BOM
```json
POST /formulas
{ "formula_id": "F-001", "formula_name": "Valve Body Mix", "product_id": "P-001" }

POST /formulas/F-001/ingredients
{ "material_id": "MAT-001", "quantity": 2.5,  "unit": "kg" }
POST /formulas/F-001/ingredients
{ "material_id": "MAT-002", "quantity": 0.08, "unit": "kg" }
POST /formulas/F-001/ingredients
{ "material_id": "MAT-005", "quantity": 1.0,  "unit": "L"  }

PUT /products/P-001/bom
{ "formula_id": "F-001", "process_id": "PRC-001" }
```

### P-002 Precision Gear Set BOM
```json
POST /formulas
{ "formula_id": "F-002", "formula_name": "Gear Set Steel Mix", "product_id": "P-002" }

POST /formulas/F-002/ingredients
{ "material_id": "MAT-003", "quantity": 3.2, "unit": "kg" }
POST /formulas/F-002/ingredients
{ "material_id": "MAT-006", "quantity": 0.5, "unit": "L"  }

PUT /products/P-002/bom
{ "formula_id": "F-002", "process_id": "PRC-002" }
```

### P-003 Hydraulic Cylinder Rod BOM
```json
POST /formulas
{ "formula_id": "F-003", "formula_name": "Cylinder Rod BOM", "product_id": "P-003" }

POST /formulas/F-003/ingredients
{ "material_id": "MAT-004", "quantity": 4.0, "unit": "kg" }
POST /formulas/F-003/ingredients
{ "material_id": "MAT-007", "quantity": 0.3, "unit": "L"  }

PUT /products/P-003/bom
{ "formula_id": "F-003", "process_id": "PRC-003" }
```

---

## 6. Inventory / Materials (14 materials)

```json
POST /inventory/materials
{ "material_id": "MAT-001", "material_name": "Carbon Steel Bar Ø50mm",   "unit": "kg",  "current_stock": 850,  "min_stock": 200, "storage_area": "Rack-A1", "status": "in_stock"    }

POST /inventory/materials
{ "material_id": "MAT-002", "material_name": "Stainless Steel Sheet 2mm","unit": "kg",  "current_stock": 120,  "min_stock": 150, "storage_area": "Rack-A2", "status": "low_stock"   }

POST /inventory/materials
{ "material_id": "MAT-003", "material_name": "Alloy Steel Billet 4140",  "unit": "kg",  "current_stock": 620,  "min_stock": 300, "storage_area": "Rack-A3", "status": "in_stock"    }

POST /inventory/materials
{ "material_id": "MAT-004", "material_name": "Chrome Steel Rod Ø60mm",   "unit": "kg",  "current_stock": 290,  "min_stock": 100, "storage_area": "Rack-B1", "status": "in_stock"    }

POST /inventory/materials
{ "material_id": "MAT-005", "material_name": "Epoxy Coating Agent",       "unit": "L",   "current_stock": 45,   "min_stock": 50,  "storage_area": "Chem-01", "status": "low_stock"   }

POST /inventory/materials
{ "material_id": "MAT-006", "material_name": "Cutting Oil (Premium)",     "unit": "L",   "current_stock": 380,  "min_stock": 100, "storage_area": "Chem-02", "status": "in_stock"    }

POST /inventory/materials
{ "material_id": "MAT-007", "material_name": "Chrome Plating Solution",   "unit": "L",   "current_stock": 0,    "min_stock": 80,  "storage_area": "Chem-03", "status": "out_of_stock"}

POST /inventory/materials
{ "material_id": "MAT-008", "material_name": "Aluminium Alloy A380",      "unit": "kg",  "current_stock": 1100, "min_stock": 400, "storage_area": "Rack-C1", "status": "in_stock"    }

POST /inventory/materials
{ "material_id": "MAT-009", "material_name": "Cast Iron EN-GJL-250",      "unit": "kg",  "current_stock": 740,  "min_stock": 250, "storage_area": "Rack-C2", "status": "in_stock"    }

POST /inventory/materials
{ "material_id": "MAT-010", "material_name": "M8 Hex Bolt (Box 500)",     "unit": "pcs", "current_stock": 2400, "min_stock": 500, "storage_area": "Bin-D1",  "status": "in_stock"    }

POST /inventory/materials
{ "material_id": "MAT-011", "material_name": "O-Ring Kit (Hydraulic)",    "unit": "set", "current_stock": 85,   "min_stock": 30,  "storage_area": "Bin-D2",  "status": "in_stock"    }

POST /inventory/materials
{ "material_id": "MAT-012", "material_name": "Powder Coat (RAL 7016)",    "unit": "kg",  "current_stock": 38,   "min_stock": 40,  "storage_area": "Chem-04", "status": "low_stock"   }

POST /inventory/materials
{ "material_id": "MAT-013", "material_name": "Bearing SKF 6205",          "unit": "pcs", "current_stock": 120,  "min_stock": 50,  "storage_area": "Bin-E1",  "status": "in_stock"    }

POST /inventory/materials
{ "material_id": "MAT-014", "material_name": "Hydraulic Seal Set",        "unit": "set", "current_stock": 44,   "min_stock": 20,  "storage_area": "Bin-E2",  "status": "in_stock"    }
```

---

## 7. Jobs (10 jobs — mix of statuses)

```json
POST /jobs
{
  "job_id": "JOB-2401",
  "product_id": "P-001",
  "quantity_total": 500,
  "priority": "high",
  "deadline": "2026-02-28T17:00:00Z",
  "status": "in-progress",
  "slots": [
    { "machine_id": "M-CNC-01", "start_time": "2026-02-10T08:00:00Z", "duration_mins": 90,  "quantity": 500 },
    { "machine_id": "M-CNC-01", "start_time": "2026-02-10T10:00:00Z", "duration_mins": 60,  "quantity": 500 },
    { "machine_id": "M-LTH-01", "start_time": "2026-02-11T08:00:00Z", "duration_mins": 45,  "quantity": 500 },
    { "machine_id": "M-CTG-01", "start_time": "2026-02-12T08:00:00Z", "duration_mins": 120, "quantity": 500 },
    { "machine_id": "M-ASM-01", "start_time": "2026-02-13T08:00:00Z", "duration_mins": 60,  "quantity": 500 }
  ]
}

POST /jobs
{
  "job_id": "JOB-2402",
  "product_id": "P-002",
  "quantity_total": 200,
  "priority": "medium",
  "deadline": "2026-03-05T17:00:00Z",
  "status": "scheduled",
  "slots": [
    { "machine_id": "M-LTH-01", "start_time": "2026-02-17T08:00:00Z", "duration_mins": 75,  "quantity": 200 },
    { "machine_id": "M-CNC-02", "start_time": "2026-02-18T08:00:00Z", "duration_mins": 120, "quantity": 200 },
    { "machine_id": "M-QC-01",  "start_time": "2026-02-18T11:00:00Z", "duration_mins": 30,  "quantity": 200 }
  ]
}

POST /jobs
{
  "job_id": "JOB-2403",
  "product_id": "P-003",
  "quantity_total": 350,
  "priority": "high",
  "deadline": "2026-02-25T17:00:00Z",
  "status": "delayed",
  "slots": [
    { "machine_id": "M-LTH-02", "start_time": "2026-02-08T08:00:00Z", "duration_mins": 50,  "quantity": 350 },
    { "machine_id": "M-CTG-01", "start_time": "2026-02-09T08:00:00Z", "duration_mins": 150, "quantity": 350 },
    { "machine_id": "M-QC-01",  "start_time": "2026-02-10T14:00:00Z", "duration_mins": 20,  "quantity": 350 }
  ]
}

POST /jobs
{
  "job_id": "JOB-2404",
  "product_id": "P-004",
  "quantity_total": 120,
  "priority": "medium",
  "deadline": "2026-03-10T17:00:00Z",
  "status": "scheduled",
  "slots": [
    { "machine_id": "M-CNC-01", "start_time": "2026-02-20T08:00:00Z", "duration_mins": 60,  "quantity": 120 },
    { "machine_id": "M-CNC-02", "start_time": "2026-02-20T10:30:00Z", "duration_mins": 45,  "quantity": 120 },
    { "machine_id": "M-CTG-01", "start_time": "2026-02-21T08:00:00Z", "duration_mins": 90,  "quantity": 120 },
    { "machine_id": "M-ASM-01", "start_time": "2026-02-21T11:00:00Z", "duration_mins": 40,  "quantity": 120 }
  ]
}

POST /jobs
{
  "job_id": "JOB-2405",
  "product_id": "P-005",
  "quantity_total": 800,
  "priority": "low",
  "deadline": "2026-03-20T17:00:00Z",
  "status": "scheduled",
  "slots": [
    { "machine_id": "M-PRS-01", "start_time": "2026-02-24T08:00:00Z", "duration_mins": 60, "quantity": 800 },
    { "machine_id": "M-CTG-01", "start_time": "2026-02-25T08:00:00Z", "duration_mins": 90, "quantity": 800 }
  ]
}

POST /jobs
{
  "job_id": "JOB-2406",
  "product_id": "P-006",
  "quantity_total": 60,
  "priority": "high",
  "deadline": "2026-02-20T17:00:00Z",
  "status": "in-progress",
  "slots": [
    { "machine_id": "M-CNC-02", "start_time": "2026-02-11T08:00:00Z", "duration_mins": 120, "quantity": 60 },
    { "machine_id": "M-ASM-01", "start_time": "2026-02-12T08:00:00Z", "duration_mins": 90,  "quantity": 60 }
  ]
}

POST /jobs
{
  "job_id": "JOB-2407",
  "product_id": "P-001",
  "quantity_total": 300,
  "priority": "medium",
  "deadline": "2026-04-01T17:00:00Z",
  "status": "scheduled",
  "slots": [
    { "machine_id": "M-CNC-01", "start_time": "2026-03-03T08:00:00Z", "duration_mins": 90, "quantity": 300 },
    { "machine_id": "M-LTH-01", "start_time": "2026-03-04T08:00:00Z", "duration_mins": 45, "quantity": 300 },
    { "machine_id": "M-ASM-01", "start_time": "2026-03-05T08:00:00Z", "duration_mins": 60, "quantity": 300 }
  ]
}

POST /jobs
{
  "job_id": "JOB-2408",
  "product_id": "P-002",
  "quantity_total": 450,
  "priority": "high",
  "deadline": "2026-04-05T17:00:00Z",
  "status": "scheduled",
  "slots": [
    { "machine_id": "M-LTH-02", "start_time": "2026-03-10T08:00:00Z", "duration_mins": 75,  "quantity": 450 },
    { "machine_id": "M-CNC-01", "start_time": "2026-03-11T08:00:00Z", "duration_mins": 120, "quantity": 450 }
  ]
}

POST /jobs
{
  "job_id": "JOB-2409",
  "product_id": "P-003",
  "quantity_total": 180,
  "priority": "low",
  "deadline": "2026-04-15T17:00:00Z",
  "status": "completed",
  "slots": [
    { "machine_id": "M-LTH-01", "start_time": "2026-01-20T08:00:00Z", "duration_mins": 50,  "quantity": 180 },
    { "machine_id": "M-CTG-01", "start_time": "2026-01-21T08:00:00Z", "duration_mins": 150, "quantity": 180 },
    { "machine_id": "M-QC-01",  "start_time": "2026-01-22T08:00:00Z", "duration_mins": 20,  "quantity": 180 }
  ]
}

POST /jobs
{
  "job_id": "JOB-2410",
  "product_id": "P-004",
  "quantity_total": 90,
  "priority": "medium",
  "deadline": "2026-02-15T17:00:00Z",
  "status": "completed",
  "slots": [
    { "machine_id": "M-CNC-01", "start_time": "2026-01-28T08:00:00Z", "duration_mins": 60, "quantity": 90 },
    { "machine_id": "M-CTG-01", "start_time": "2026-01-29T09:00:00Z", "duration_mins": 90, "quantity": 90 },
    { "machine_id": "M-ASM-01", "start_time": "2026-01-30T08:00:00Z", "duration_mins": 40, "quantity": 90 }
  ]
}
```

---

## 8. Production Logs (for completed/in-progress jobs)

```json
POST /production-logs
{ "slot_id": "slot-2409-1", "job_id": "JOB-2409", "machine_id": "M-LTH-01", "qty_produced": 180, "qty_scrap": 3,  "downtime_mins": 0,  "notes": "Smooth run, minor chatter on finish pass" }

POST /production-logs
{ "slot_id": "slot-2409-2", "job_id": "JOB-2409", "machine_id": "M-CTG-01", "qty_produced": 177, "qty_scrap": 2,  "downtime_mins": 15, "notes": "Brief downtime – solution temperature adjustment" }

POST /production-logs
{ "slot_id": "slot-2410-1", "job_id": "JOB-2410", "machine_id": "M-CNC-01", "qty_produced": 90,  "qty_scrap": 1,  "downtime_mins": 0,  "notes": "All within spec" }

POST /production-logs
{ "slot_id": "slot-2410-3", "job_id": "JOB-2410", "machine_id": "M-ASM-01", "qty_produced": 89,  "qty_scrap": 1,  "downtime_mins": 0,  "notes": "One housing had hairline crack, scrapped" }

POST /production-logs
{ "slot_id": "slot-2401-1", "job_id": "JOB-2401", "machine_id": "M-CNC-01", "qty_produced": 250, "qty_scrap": 5,  "downtime_mins": 10, "notes": "Coolant pump warning at 1hr mark" }
```

---

## 9. Quality Inspections

```json
POST /quality/inspections
{ "job_id": "JOB-2409", "slot_id": "slot-2409-3", "machine_id": "M-QC-01", "result": "pass",        "defect_count": 0, "notes": "All 177 rods within chrome thickness spec (15–20 µm)" }

POST /quality/inspections
{ "job_id": "JOB-2410", "slot_id": "slot-2410-3", "machine_id": "M-QC-01", "result": "conditional",  "defect_count": 1, "notes": "89/90 pass. 1 unit scrapped for hairline surface crack. Batch approved." }

POST /quality/inspections
{ "job_id": "JOB-2401", "slot_id": "slot-2401-1", "machine_id": "M-QC-01", "result": "pass",        "defect_count": 3, "notes": "3 cosmetic blemishes, within customer tolerance" }
```

---

## 10. Maintenance Records

```json
POST /maintenance
{ "machine_id": "M-CTG-01", "maintenance_type": "Scheduled", "technician": "Ahmad Zaki",     "start_time": "2026-02-01T08:00:00Z", "end_time": "2026-02-01T16:00:00Z", "notes": "Replaced spray nozzles, recalibrated temperature controller. Coating solution refreshed." }

POST /maintenance
{ "machine_id": "M-LTH-02", "maintenance_type": "Preventive", "technician": "Lee Wei Hao",   "start_time": "2025-12-28T08:00:00Z", "end_time": "2025-12-28T12:00:00Z", "notes": "Spindle bearing lubrication, chuck jaw replacement" }

POST /maintenance
{ "machine_id": "M-CNC-01", "maintenance_type": "Preventive", "technician": "Rajan Kumar",   "start_time": "2026-01-15T07:00:00Z", "end_time": "2026-01-15T11:00:00Z", "notes": "Tool magazine cleaned, ATC arm calibrated, spindle alignment verified" }

POST /machines/downtime
{ "machine_id": "M-CNC-01", "start_time": "2026-02-10T09:00:00Z", "end_time": "2026-02-10T09:10:00Z", "reason": "Coolant pump low pressure alarm", "reported_by": "Operator A" }

POST /machines/downtime
{ "machine_id": "M-CTG-01", "start_time": "2026-02-09T10:30:00Z", "end_time": "2026-02-09T10:45:00Z", "reason": "Coating solution temperature out of range – auto-shutdown", "reported_by": "Operator B" }
```

---

## 11. Settings

```json
PUT /settings
{
  "language": "English",
  "timezone": "UTC+8",
  "simulation_mode": false,
  "auto_save_interval": 30,
  "data_retention_days": 90,
  "notifications": {
    "job_complete":       true,
    "maintenance_alert":  true,
    "low_stock":          true,
    "downtime":           true,
    "email_enabled":      false,
    "push_enabled":       true
  },
  "erp_integration": {
    "system":    "",
    "endpoint":  "",
    "status":    "disconnected",
    "last_sync": null
  }
}
```

---

## 12. Expected Report Responses (shape reference)

When the frontend calls `GET /reports/*`, it should return these shapes so charts render correctly:

### GET /reports/production-output
```json
{
  "total_units": 24180,
  "change_pct": 5.2,
  "data": [
    { "label": "Mon", "units": 3200 },
    { "label": "Tue", "units": 3800 },
    { "label": "Wed", "units": 4100 },
    { "label": "Thu", "units": 3600 },
    { "label": "Fri", "units": 4200 },
    { "label": "Sat", "units": 2900 },
    { "label": "Sun", "units": 2380 }
  ]
}
```

### GET /reports/machine-utilization
```json
{
  "avg_pct": 85.2,
  "change_pct": -1.8,
  "data": [
    { "machine_id": "M-CNC-01", "machine_name": "CNC Mill 01",          "utilization_pct": 92 },
    { "machine_id": "M-CNC-02", "machine_name": "CNC Mill 02",          "utilization_pct": 88 },
    { "machine_id": "M-LTH-01", "machine_name": "Lathe 01",             "utilization_pct": 78 },
    { "machine_id": "M-LTH-02", "machine_name": "Lathe 02",             "utilization_pct": 65 },
    { "machine_id": "M-PRS-01", "machine_name": "Hydraulic Press 01",   "utilization_pct": 85 },
    { "machine_id": "M-CTG-01", "machine_name": "Coating Station 01",   "utilization_pct": 42 },
    { "machine_id": "M-ASM-01", "machine_name": "Assembly Station 01",  "utilization_pct": 91 }
  ]
}
```

### GET /reports/job-completion
```json
{
  "total_jobs": 10,
  "change_pct": 2.1,
  "data": [
    { "job_id": "JOB-2401", "product_name": "Valve Body Assembly",   "status": "in-progress", "planned_deadline": "2026-02-28", "completion_pct": 60 },
    { "job_id": "JOB-2402", "product_name": "Precision Gear Set",    "status": "scheduled",   "planned_deadline": "2026-03-05", "completion_pct": 0  },
    { "job_id": "JOB-2403", "product_name": "Hydraulic Cylinder Rod","status": "delayed",     "planned_deadline": "2026-02-25", "completion_pct": 30 },
    { "job_id": "JOB-2409", "product_name": "Hydraulic Cylinder Rod","status": "completed",   "planned_deadline": "2026-04-15", "completion_pct": 100},
    { "job_id": "JOB-2410", "product_name": "Motor Housing",         "status": "completed",   "planned_deadline": "2026-02-15", "completion_pct": 100}
  ]
}
```

### GET /reports/oee
```json
{
  "avg_oee": 85.2,
  "data": [
    { "date": "2026-02-05", "oee": 82.1, "availability": 91, "performance": 88, "quality": 98 },
    { "date": "2026-02-06", "oee": 84.5, "availability": 93, "performance": 89, "quality": 97 },
    { "date": "2026-02-07", "oee": 86.2, "availability": 95, "performance": 90, "quality": 99 },
    { "date": "2026-02-08", "oee": 83.8, "availability": 90, "performance": 87, "quality": 98 },
    { "date": "2026-02-09", "oee": 88.0, "availability": 96, "performance": 91, "quality": 99 },
    { "date": "2026-02-10", "oee": 85.7, "availability": 94, "performance": 89, "quality": 98 },
    { "date": "2026-02-11", "oee": 87.1, "availability": 95, "performance": 90, "quality": 99 }
  ]
}
```

### GET /reports/bottlenecks
```json
{
  "total_hours": 18.5,
  "change_pct": 8.0,
  "data": [
    { "cause": "Unscheduled Maintenance", "hours": 8.3,  "pct": 45 },
    { "cause": "Material Shortage",       "hours": 4.1,  "pct": 22 },
    { "cause": "Setup & Changeover",      "hours": 3.2,  "pct": 17 },
    { "cause": "Operator Absence",        "hours": 1.9,  "pct": 10 },
    { "cause": "Quality Rework",          "hours": 1.0,  "pct": 6  }
  ]
}
```

### GET /machines/maintenance-alerts
```json
[
  { "machine_id": "M-LTH-02", "machine_name": "Lathe 02",            "days_until_due": 3,  "last_maintenance": "2025-12-28", "alert_level": "critical" },
  { "machine_id": "M-PRS-01", "machine_name": "Hydraulic Press 01",  "days_until_due": 6,  "last_maintenance": "2025-12-01", "alert_level": "warning"  },
  { "machine_id": "M-CNC-02", "machine_name": "CNC Mill 02",         "days_until_due": 12, "last_maintenance": "2026-01-20", "alert_level": "info"     }
]
```

### GET /settings
```json
{
  "language": "English",
  "timezone": "UTC+8",
  "simulation_mode": false,
  "auto_save_interval": 30,
  "data_retention_days": 90,
  "notifications": {
    "job_complete": true,
    "maintenance_alert": true,
    "low_stock": true,
    "downtime": true,
    "email_enabled": false,
    "push_enabled": true
  },
  "erp_integration": {
    "system": "",
    "endpoint": "",
    "status": "disconnected",
    "last_sync": null
  }
}
```

---

## Summary

| Entity              | Count |
|---------------------|-------|
| Machines            | 8     |
| Products            | 6     |
| Processes + Steps   | 4 processes, 16 steps |
| Formulas + BOM      | 3 formulas |
| Materials           | 14    |
| Jobs                | 10    |
| Production Logs     | 5     |
| Quality Inspections | 3     |
| Maintenance Records | 5     |
