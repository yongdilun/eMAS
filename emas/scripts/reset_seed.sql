-- Full reset before re-seeding. Run against your emas database.
-- After running, execute: go run ./cmd/seed
-- This repopulates with current-date-relative data (e.g. job deadlines 7-14 days ahead).

-- Disable FK checks (if any) for clean truncate
SET FOREIGN_KEY_CHECKS = 0;

-- Child tables first (order respects FKs: formula_ingredients before formula, process_step_materials before process_steps)
DELETE FROM job_step_schedule_slots;
DELETE FROM production_logs;
DELETE FROM quality_inspection_records;
DELETE FROM job_steps;
DELETE FROM ai_proposals;
DELETE FROM jobs;
DELETE FROM machine_capabilities;
DELETE FROM inventory_expected_arrivals;
DELETE FROM inventory_reservations;
DELETE FROM product_inventory;
DELETE FROM formula_ingredients;
DELETE FROM product_bom;
DELETE FROM process_step_materials;
DELETE FROM process_steps;
DELETE FROM product_process;
DELETE FROM machine_calendar;
DELETE FROM formula;
DELETE FROM inventory_transactions;
DELETE FROM inventory_materials;
DELETE FROM machines;
DELETE FROM maintenance_records;
DELETE FROM machine_downtime;
DELETE FROM resource_calendar;
DELETE FROM step_resource_requirements;
DELETE FROM resources;
DELETE FROM machine_setup_rules;
DELETE FROM scheduling_events;

-- Products (has formula_id now)
DELETE FROM products;

-- Re-enable FK checks
SET FOREIGN_KEY_CHECKS = 1;
