// Seed command populates MySQL with mock data from MOCK_DATA_SEED.md
package main

import (
	"emas/config"
	"emas/internal/domain"
	"emas/internal/repository"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"emas/pkg/id"
	"gorm.io/gorm"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatal("config:", err)
	}
	db, err := repository.InitDB(cfg)
	if err != nil {
		log.Fatal("db:", err)
	}
	if err := repository.AutoMigrate(db); err != nil {
		log.Fatal("migrate:", err)
	}

	log.Println("Seeding reference data...")
	seedReferenceData(db)

	log.Println("Seeding machines...")
	seedMachines(db)

	log.Println("Seeding formulas and ingredients...")
	seedFormulas(db)

	log.Println("Seeding processes and steps...")
	steps := seedProcesses(db)

	log.Println("Seeding products...")
	seedProducts(db)

	log.Println("Seeding process step gaps (MinWait, Transfer, Batch, Predecessors)...")
	seedProcessStepGaps(db)

	log.Println("Seeding machine capabilities...")
	seedCapabilities(db, steps)

	log.Println("Seeding machine setup rules...")
	seedMachineSetupRules(db)

	log.Println("Seeding resources...")
	seedResources(db)

	log.Println("Seeding materials...")
	seedMaterials(db)

	log.Println("Seeding expected arrivals...")
	seedExpectedArrivals(db)

	log.Println("Seeding product inventory...")
	seedProductInventory(db)

	log.Println("Seeding inventory reservations...")
	seedInventoryReservations(db)

	log.Println("Seeding process step materials...")
	seedProcessStepMaterials(db)

	log.Println("Seeding BOM...")
	seedBOM(db)

	log.Println("Validating BOM consistency...")
	validateBOMConsistency(db)

	log.Println("Seeding jobs...")
	jobSlots := seedJobs(db)

	log.Println("Seeding WIP inventory...")
	seedWIPInventory(db)

	log.Println("Seeding AI proposals...")
	seedAIProposals(db, jobSlots)

	log.Println("Seeding production logs...")
	seedProductionLogs(db, jobSlots)

	log.Println("Seeding quality inspections...")
	seedQuality(db, jobSlots)

	log.Println("Seeding maintenance and downtime...")
	seedMaintenance(db)

	log.Println("Seeding scheduling settings (work template)...")
	seedSchedulingSettings(db)

	log.Println("Seed completed.")
}

func seedSchedulingSettings(db *gorm.DB) {
	settingsRepo := repository.NewSystemSettingsRepository(db)
	// Seed demo data should be schedulable on the same day even when the reset/seed
	// command is run late in the afternoon. We therefore use a broad 7-day work
	// template and no reschedule lock window by default for seeded environments.
	_ = settingsRepo.PutInt("scheduling.lock_in_window_minutes", 0)
	_ = settingsRepo.PutString("scheduling.work_start_time", "00:00")
	_ = settingsRepo.PutString("scheduling.work_end_time", "23:30")
	_ = settingsRepo.PutString("scheduling.work_days", "0,1,2,3,4,5,6")
	_ = settingsRepo.PutString("scheduling.public_holidays", "[]")
}

func seedMachines(db *gorm.DB) {
	machines := []domain.Machine{
		{MachineID: "M-CNC-01", MachineName: "CNC Mill 01", MachineType: "CNC Mill", Status: domain.MachineStatusRunning, CapacityPerHour: 200, MaintenanceIntervalDays: 30, Location: "Floor A – Bay 1", LastMaintenanceDate: ptr(parseDate("2026-01-15"))},
		{MachineID: "M-CNC-02", MachineName: "CNC Mill 02", MachineType: "CNC Mill", Status: domain.MachineStatusRunning, CapacityPerHour: 200, MaintenanceIntervalDays: 30, Location: "Floor A – Bay 2", LastMaintenanceDate: ptr(parseDate("2026-01-20"))},
		{MachineID: "M-LTH-01", MachineName: "Lathe 01", MachineType: "CNC Lathe", Status: domain.MachineStatusRunning, CapacityPerHour: 150, MaintenanceIntervalDays: 45, Location: "Floor B – Bay 1", LastMaintenanceDate: ptr(parseDate("2026-01-10"))},
		{MachineID: "M-LTH-02", MachineName: "Lathe 02", MachineType: "CNC Lathe", Status: domain.MachineStatusIdle, CapacityPerHour: 150, MaintenanceIntervalDays: 45, Location: "Floor B – Bay 2", LastMaintenanceDate: ptr(parseDate("2025-12-28"))},
		{MachineID: "M-PRS-01", MachineName: "Hydraulic Press 01", MachineType: "Hydraulic Press", Status: domain.MachineStatusRunning, CapacityPerHour: 300, MaintenanceIntervalDays: 60, Location: "Floor C – Bay 1", LastMaintenanceDate: ptr(parseDate("2025-12-01"))},
		{MachineID: "M-CTG-01", MachineName: "Coating Station 01", MachineType: "Coating Station", Status: domain.MachineStatusRunning, CapacityPerHour: 100, MaintenanceIntervalDays: 14, Location: "Paint Shop", LastMaintenanceDate: ptr(parseDate("2026-02-01"))},
		{MachineID: "M-PRS-02", MachineName: "Hydraulic Press 02", MachineType: "Hydraulic Press", Status: domain.MachineStatusRunning, CapacityPerHour: 280, MaintenanceIntervalDays: 60, Location: "Floor C – Bay 2", LastMaintenanceDate: ptr(parseDate("2026-01-10"))},
		{MachineID: "M-CTG-02", MachineName: "Coating Station 02", MachineType: "Coating Station", Status: domain.MachineStatusRunning, CapacityPerHour: 90, MaintenanceIntervalDays: 14, Location: "Paint Shop", LastMaintenanceDate: ptr(parseDate("2026-02-05"))},
		{MachineID: "M-ASM-01", MachineName: "Assembly Station 01", MachineType: "Assembly Station", Status: domain.MachineStatusRunning, CapacityPerHour: 250, MaintenanceIntervalDays: 90, Location: "Floor A – Bay 3", LastMaintenanceDate: ptr(parseDate("2026-01-05"))},
		{MachineID: "M-QC-01", MachineName: "Quality Control Station", MachineType: "Quality Control Station", Status: domain.MachineStatusRunning, CapacityPerHour: 500, MaintenanceIntervalDays: 180, Location: "Quality Lab", LastMaintenanceDate: ptr(parseDate("2025-11-01"))},
	}
	for _, m := range machines {
		_ = db.Where(domain.Machine{MachineID: m.MachineID}).FirstOrCreate(&m)
	}
}

func seedProducts(db *gorm.DB) {
	now := time.Now()
	products := []domain.Product{
		{ProductID: "P-001", ProductName: "Valve Body Assembly", ProductType: "Hydraulic Components", UnitOfMeasure: "pcs", Description: "High-pressure valve body used in industrial hydraulic systems", Status: domain.ProductStatusActive, FormulaID: "F-001", ProcessID: "PRC-001", CreatedAt: now},
		{ProductID: "P-002", ProductName: "Precision Gear Set", ProductType: "Power Transmission", UnitOfMeasure: "set", Description: "Hardened steel gear set for industrial gearboxes", Status: domain.ProductStatusActive, FormulaID: "F-002", ProcessID: "PRC-002", CreatedAt: now},
		{ProductID: "P-003", ProductName: "Hydraulic Cylinder Rod", ProductType: "Hydraulic Components", UnitOfMeasure: "pcs", Description: "Chrome-plated cylinder rod, 50mm diameter, 400mm stroke", Status: domain.ProductStatusActive, FormulaID: "F-003", ProcessID: "PRC-003", CreatedAt: now},
		{ProductID: "P-004", ProductName: "Motor Housing", ProductType: "Electrical Enclosures", UnitOfMeasure: "pcs", Description: "Die-cast aluminium housing for 15kW induction motors", Status: domain.ProductStatusActive, FormulaID: "F-004", ProcessID: "PRC-004", CreatedAt: now},
		{ProductID: "P-005", ProductName: "Control Bracket", ProductType: "Structural Parts", UnitOfMeasure: "pcs", Description: "Mounting bracket for control panel assemblies", Status: domain.ProductStatusActive, FormulaID: "F-005", ProcessID: "PRC-005", CreatedAt: now},
		{ProductID: "P-006", ProductName: "Pump Casing", ProductType: "Fluid Handling", UnitOfMeasure: "pcs", Description: "Cast iron pump casing for centrifugal pumps, 3-inch port", Status: domain.ProductStatusActive, FormulaID: "F-006", ProcessID: "PRC-006", CreatedAt: now},
		{ProductID: "P-007", ProductName: "Seal Kit", ProductType: "Assembly / Sub-assembly", UnitOfMeasure: "set", Description: "O-rings and seals for valve body assembly", Status: domain.ProductStatusActive, FormulaID: "F-007", ProcessID: "PRC-007", CreatedAt: now},
		{ProductID: "P-008", ProductName: "Valve Spool Assembly", ProductType: "Assembly / Sub-assembly", UnitOfMeasure: "pcs", Description: "Precision spool and sleeve for valve body", Status: domain.ProductStatusActive, FormulaID: "F-008", ProcessID: "PRC-008", CreatedAt: now},
		{ProductID: "P-009", ProductName: "Pump Gasket Set", ProductType: "Assembly / Sub-assembly", UnitOfMeasure: "set", Description: "Gaskets and seal rings for pump casing", Status: domain.ProductStatusActive, FormulaID: "F-009", ProcessID: "PRC-009", CreatedAt: now},
	}
	for _, p := range products {
		_ = db.Save(&p) // Save overwrites product_name etc so "Big product" -> "Seal Kit"
	}
}

func seedProcesses(db *gorm.DB) map[string]string {
	steps := map[string]string{}
	now := time.Now()

	createProcessAndSteps := func(procID, productID, procName string, stepSpecs []struct {
		name, machineType string
		dur               int
	}) {
		proc := domain.ProductProcess{ProcessID: procID, ProductID: productID, ProcessName: procName, Version: 1, EffectiveFrom: &now, IsPrimary: true}
		_ = db.Where(domain.ProductProcess{ProcessID: procID}).Attrs(domain.ProductProcess{EffectiveFrom: &now, IsPrimary: true}).FirstOrCreate(&proc)
		_ = db.Model(&proc).Where("process_id = ? AND effective_from IS NULL", procID).Update("effective_from", now)
		for i, s := range stepSpecs {
			sid := fmt.Sprintf("STP-%s-%d", strings.ReplaceAll(productID, "-", ""), i+1) // P-001 -> P001 -> STP-P001-1
			st := domain.ProcessSteps{StepID: sid, ProcessID: procID, StepSequence: i + 1, StepName: s.name, StepType: s.name, MachineTypeRequired: s.machineType, DefaultProcessingTime: s.dur}
			_ = db.Save(&st) // upsert so step_type gets set on re-seed
			steps[sid] = procID
		}
	}

	createProcessAndSteps("PRC-001", "P-001", "Valve Body Standard Routing", []struct {
		name, machineType string
		dur               int
	}{
		{"CNC Rough Milling", "CNC Mill", 90},
		{"CNC Finish Milling", "CNC Mill", 60},
		{"Turning – Bore", "CNC Lathe", 45},
		{"Surface Coating", "Coating Station", 120},
		{"Final Assembly & Test", "Assembly Station", 60},
	})
	createProcessAndSteps("PRC-002", "P-002", "Gear Set Precision Routing", []struct {
		name, machineType string
		dur               int
	}{
		{"Gear Blank Turning", "CNC Lathe", 75},
		{"Hobbing / CNC Mill", "CNC Mill", 120},
		{"Gear Inspection", "Quality Control Station", 30},
	})
	createProcessAndSteps("PRC-003", "P-003", "Cylinder Rod Routing", []struct {
		name, machineType string
		dur               int
	}{
		{"Bar Turning", "CNC Lathe", 50},
		{"Chrome Plating", "Coating Station", 150},
		{"Final Inspection", "Quality Control Station", 20},
	})
	createProcessAndSteps("PRC-004", "P-004", "Motor Housing Routing", []struct {
		name, machineType string
		dur               int
	}{
		{"Rough Boring", "CNC Mill", 60},
		{"Drilling & Tapping", "CNC Mill", 45},
		{"Powder Coating", "Coating Station", 90},
		{"Assembly & QC", "Assembly Station", 40},
	})
	createProcessAndSteps("PRC-005", "P-005", "Control Bracket Routing", []struct {
		name, machineType string
		dur               int
	}{
		{"Stamping", "Hydraulic Press", 30},
		{"Powder Coating", "Coating Station", 45},
	})
	createProcessAndSteps("PRC-006", "P-006", "Pump Casing Routing", []struct {
		name, machineType string
		dur               int
	}{
		{"Casting", "Hydraulic Press", 90},
		{"CNC Bore & Face", "CNC Mill", 60},
		{"Assembly & QC", "Assembly Station", 45},
	})
	createProcessAndSteps("PRC-007", "P-007", "Seal Kit Assembly", []struct {
		name, machineType string
		dur               int
	}{
		{"Kit Assembly", "Assembly Station", 15},
		{"QC Inspection", "Quality Control Station", 10},
	})
	createProcessAndSteps("PRC-008", "P-008", "Valve Spool Routing", []struct {
		name, machineType string
		dur               int
	}{
		{"Precision Turning", "CNC Lathe", 55},
		{"Grinding & Honing", "CNC Mill", 40},
		{"Inspection", "Quality Control Station", 15},
	})
	createProcessAndSteps("PRC-009", "P-009", "Gasket Set Assembly", []struct {
		name, machineType string
		dur               int
	}{
		{"Gasket Cutting", "Assembly Station", 25},
		{"Kit Assembly & QC", "Quality Control Station", 12},
	})

	return steps
}

func seedProcessStepGaps(db *gorm.DB) {
	// MinWaitMinutes, TransferMinutes, BatchSize, IsBatchProcess, MinBatchSize, PredecessorStepIDs
	type stepUpdate struct {
		StepID             string
		MinWaitMinutes     int
		TransferMinutes    int
		BatchSize          int
		MinBatchSize       int
		IsBatchProcess     bool
		PredecessorStepIDs string
	}
	updates := []stepUpdate{
		// Coating steps: cooling time, batch process
		{StepID: "STP-P001-4", MinWaitMinutes: 15, TransferMinutes: 10, BatchSize: 100, MinBatchSize: 50, IsBatchProcess: true, PredecessorStepIDs: `["STP-P001-3"]`},
		{StepID: "STP-P003-2", MinWaitMinutes: 15, TransferMinutes: 10, BatchSize: 100, MinBatchSize: 50, IsBatchProcess: true, PredecessorStepIDs: `["STP-P003-1"]`},
		{StepID: "STP-P004-3", MinWaitMinutes: 15, TransferMinutes: 10, BatchSize: 100, MinBatchSize: 50, IsBatchProcess: true, PredecessorStepIDs: `["STP-P004-2"]`},
		{StepID: "STP-P005-2", MinWaitMinutes: 15, TransferMinutes: 10, BatchSize: 100, MinBatchSize: 50, IsBatchProcess: true, PredecessorStepIDs: `["STP-P005-1"]`},
		// Transfer time between steps (others)
		{StepID: "STP-P001-1", TransferMinutes: 10, PredecessorStepIDs: ""},
		{StepID: "STP-P001-2", MinWaitMinutes: 0, TransferMinutes: 10, PredecessorStepIDs: `["STP-P001-1"]`},
		{StepID: "STP-P001-3", MinWaitMinutes: 0, TransferMinutes: 10, PredecessorStepIDs: `["STP-P001-2"]`},
		{StepID: "STP-P001-5", MinWaitMinutes: 0, TransferMinutes: 10, PredecessorStepIDs: `["STP-P001-1","STP-P001-2","STP-P001-3","STP-P001-4"]`},
		{StepID: "STP-P002-1", TransferMinutes: 10, PredecessorStepIDs: ""},
		{StepID: "STP-P002-2", TransferMinutes: 10, PredecessorStepIDs: `["STP-P002-1"]`},
		{StepID: "STP-P002-3", TransferMinutes: 10, PredecessorStepIDs: `["STP-P002-2"]`},
		{StepID: "STP-P003-1", TransferMinutes: 10, PredecessorStepIDs: ""},
		{StepID: "STP-P003-3", TransferMinutes: 10, PredecessorStepIDs: `["STP-P003-2"]`},
		{StepID: "STP-P004-1", TransferMinutes: 10, PredecessorStepIDs: ""},
		{StepID: "STP-P004-2", TransferMinutes: 10, PredecessorStepIDs: `["STP-P004-1"]`},
		{StepID: "STP-P004-4", TransferMinutes: 10, PredecessorStepIDs: `["STP-P004-3"]`},
		{StepID: "STP-P005-1", TransferMinutes: 10, PredecessorStepIDs: ""},
		{StepID: "STP-P006-1", TransferMinutes: 10, PredecessorStepIDs: ""},
		{StepID: "STP-P006-2", TransferMinutes: 10, PredecessorStepIDs: `["STP-P006-1"]`},
		{StepID: "STP-P006-3", TransferMinutes: 10, PredecessorStepIDs: `["STP-P006-2"]`},
		{StepID: "STP-P007-1", TransferMinutes: 5, PredecessorStepIDs: ""},
		{StepID: "STP-P007-2", TransferMinutes: 5, PredecessorStepIDs: `["STP-P007-1"]`},
		{StepID: "STP-P008-1", TransferMinutes: 10, PredecessorStepIDs: ""},
		{StepID: "STP-P008-2", TransferMinutes: 10, PredecessorStepIDs: `["STP-P008-1"]`},
		{StepID: "STP-P008-3", TransferMinutes: 10, PredecessorStepIDs: `["STP-P008-2"]`},
		{StepID: "STP-P009-1", TransferMinutes: 5, PredecessorStepIDs: ""},
		{StepID: "STP-P009-2", TransferMinutes: 5, PredecessorStepIDs: `["STP-P009-1"]`},
	}
	for _, u := range updates {
		_ = db.Model(&domain.ProcessSteps{}).Where("step_id = ?", u.StepID).Updates(map[string]interface{}{
			"min_wait_minutes":     u.MinWaitMinutes,
			"transfer_minutes":     u.TransferMinutes,
			"batch_size":           u.BatchSize,
			"min_batch_size":       u.MinBatchSize,
			"is_batch_process":     u.IsBatchProcess,
			"predecessor_step_ids": u.PredecessorStepIDs,
		}).Error
	}
}

func seedMachineSetupRules(db *gorm.DB) {
	now := time.Now()
	rules := []domain.MachineSetupRule{
		{ID: "SETUP-001", MachineID: "M-CNC-01", FromProductID: "P-001", ToProductID: "P-002", SetupMinutes: 30},
		{ID: "SETUP-002", MachineID: "M-CNC-01", FromProductID: "P-002", ToProductID: "P-001", SetupMinutes: 30},
		{ID: "SETUP-003", MachineID: "M-CNC-02", FromProductID: "P-001", ToProductID: "P-004", SetupMinutes: 25},
		{ID: "SETUP-004", MachineID: "M-CTG-01", FromProductID: "P-003", ToProductID: "P-004", SetupMinutes: 45},
		{ID: "SETUP-005", MachineID: "M-CTG-01", FromProductID: "P-004", ToProductID: "P-003", SetupMinutes: 45},
	}
	for _, r := range rules {
		_ = db.Where(domain.MachineSetupRule{ID: r.ID}).FirstOrCreate(&r)
	}
	_ = now // avoid unused if needed later
}

func seedResources(db *gorm.DB) {
	now := time.Now()
	resources := []domain.Resource{
		{ResourceID: "RES-OP-01", ResourceName: "Operator A", ResourceType: domain.ResourceTypeOperator},
		{ResourceID: "RES-OP-02", ResourceName: "Operator B", ResourceType: domain.ResourceTypeOperator},
	}
	for _, r := range resources {
		_ = db.Where(domain.Resource{ResourceID: r.ResourceID}).FirstOrCreate(&r)
	}
	// StepResourceRequirement: Assembly steps require operator
	reqs := []domain.StepResourceRequirement{
		{ID: "SRR-001", StepID: "STP-P001-5", ResourceID: "RES-OP-01", Count: 1},
		{ID: "SRR-002", StepID: "STP-P004-4", ResourceID: "RES-OP-01", Count: 1},
		{ID: "SRR-003", StepID: "STP-P006-3", ResourceID: "RES-OP-01", Count: 1},
		{ID: "SRR-004", StepID: "STP-P007-1", ResourceID: "RES-OP-02", Count: 1},
	}
	for _, r := range reqs {
		_ = db.Where(domain.StepResourceRequirement{ID: r.ID}).FirstOrCreate(&r)
	}
	// ResourceCalendar: available 08:00–17:00 weekdays (use base date)
	base := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location())
	for i := 0; i < 30; i++ {
		day := base.AddDate(0, 0, i)
		if day.Weekday() == time.Saturday || day.Weekday() == time.Sunday {
			continue
		}
		start := time.Date(day.Year(), day.Month(), day.Day(), 8, 0, 0, 0, day.Location())
		end := time.Date(day.Year(), day.Month(), day.Day(), 17, 0, 0, 0, day.Location())
		for _, res := range resources {
			id := fmt.Sprintf("RC-%s-%d", res.ResourceID, i)
			cal := domain.ResourceCalendar{ID: id, ResourceID: res.ResourceID, StartTime: start, EndTime: end, AvailabilityType: "work"}
			_ = db.Where(domain.ResourceCalendar{ID: id}).FirstOrCreate(&cal)
		}
	}
}

func seedWIPInventory(db *gorm.DB) {
	now := time.Now()
	// WIP at job step output: JS-SEED-001-2 produces intermediate for step 3; STP-P008-2 produces valve spool (P-008) for P-001 assembly
	// Job steps are created per job. JOB-SEED-001 has steps JS-SEED-1-1..5. The format is JS-SEED-{suffix}-{stepNum} where suffix is "001" -> "1"
	// Actually: fmt.Sprintf("JS-SEED-%s-%d", strings.TrimPrefix(spec.jobID, "JOB-SEED-"), i+1) => JS-SEED-001-1, JS-SEED-001-2, ...
	// So for JOB-SEED-001, step 2 (STP-P001-2 CNC Finish Milling) produces output that feeds step 3. But ProcessStepMaterial shows step 5 produces P-001.
	// For P-008: STP-P008-3 is inspection; the output of the valve spool comes from the process. The ProcessStepMaterial for P-001 step 5 consumes P-008.
	// So P-008 is produced by the P-008 process (PRC-008). The job steps for a P-008 job would be STP-P008-1, STP-P008-2, STP-P008-3. Step 3 is final.
	// WIP at a job step = output of that step available for next step. For a multi-step job, step N output might feed step N+1.
	// P-001 step 5 consumes P-007 and P-008 (from other jobs). So WIP would be at job steps that produce P-007 or P-008.
	// Seed: Add WIP at JS-SEED-011-2 (P-008 job, step 2 = grinding) - output is nearly finished valve spool. Or at a step that outputs product.
	// Actually WIPInventory has JobStepID, ProductID, Quantity. So we're saying "at this job step, we have X quantity of product Y available".
	// For testing: add WIP at JS-SEED-001-2 (arbitrary) with ProductID P-008, 500 pcs - simulates partial output from a prior P-008 job available for P-001 assembly.
	wipItems := []domain.WIPInventory{
		{ID: "WIP-SEED-001", JobStepID: "JS-SEED-001-5", ProductID: strPtr("P-008"), Quantity: 500, Unit: "pcs", Location: "WIP-A1", UpdatedAt: now},
		{ID: "WIP-SEED-002", JobStepID: "JS-SEED-001-5", ProductID: strPtr("P-007"), Quantity: 300, Unit: "set", Location: "WIP-A1", UpdatedAt: now},
	}
	for _, w := range wipItems {
		_ = db.Where(domain.WIPInventory{ID: w.ID}).FirstOrCreate(&w)
	}
}

func seedCapabilities(db *gorm.DB, steps map[string]string) {
	machineSteps := map[string][]string{
		"M-CNC-01": {"STP-P001-1", "STP-P001-2", "STP-P002-2", "STP-P004-1", "STP-P004-2", "STP-P006-2", "STP-P008-2"},
		"M-CNC-02": {"STP-P001-1", "STP-P001-2", "STP-P002-2", "STP-P004-1", "STP-P004-2", "STP-P006-2", "STP-P008-2"},
		"M-LTH-01": {"STP-P001-3", "STP-P002-1", "STP-P003-1", "STP-P008-1"},
		"M-LTH-02": {"STP-P001-3", "STP-P002-1", "STP-P003-1", "STP-P008-1"},
		"M-PRS-01": {"STP-P005-1", "STP-P006-1"},
		"M-CTG-01": {"STP-P001-4", "STP-P003-2", "STP-P004-3", "STP-P005-2"},
		"M-PRS-02": {"STP-P005-1", "STP-P006-1"},
		"M-CTG-02": {"STP-P001-4", "STP-P003-2", "STP-P004-3", "STP-P005-2"},
		"M-ASM-01": {"STP-P001-5", "STP-P004-4", "STP-P006-3", "STP-P007-1", "STP-P009-1"},
		"M-QC-01":  {"STP-P002-3", "STP-P003-3", "STP-P007-2", "STP-P008-3", "STP-P009-2"},
	}
	for machineID, stepIDs := range machineSteps {
		for _, stepID := range stepIDs {
			if _, ok := steps[stepID]; !ok {
				continue
			}
			var c domain.MachineCapabilities
			_ = db.Where(domain.MachineCapabilities{MachineID: machineID, StepID: stepID}).
				Attrs(domain.MachineCapabilities{CapabilityID: id.NewPrefixed("CAP-"), EfficiencyFactor: 1.0}).
				FirstOrCreate(&c)
		}
	}
}

func seedFormulas(db *gorm.DB) {
	now := time.Now()
	_ = db.Exec("DELETE FROM formula_ingredients WHERE formula_id LIKE 'F-0%'").Error // clean before re-seed when structure changes
	spec := bomSpec()
	seenFormula := map[string]bool{}
	for _, e := range spec {
		if !seenFormula[e.FormulaID] {
			seenFormula[e.FormulaID] = true
			f := domain.Formula{FormulaID: e.FormulaID, FormulaName: e.FormulaName, Version: 1, CreatedAt: now, EffectiveFrom: &now}
			_ = db.Save(&f)
		}
		if e.Role != domain.ProcessStepMaterialRoleInput || e.IngredientID == "" {
			continue
		}
		source := e.Source
		if source == "" {
			if e.ProductIDComp != nil {
				source = domain.IngredientSourceMake
			} else {
				source = domain.IngredientSourceBuy
			}
		}
		if e.MaterialID != nil {
			ing := domain.FormulaIngredients{IngredientID: e.IngredientID, FormulaID: e.FormulaID, ComponentType: domain.ComponentTypeMaterial, MaterialID: e.MaterialID, QuantityPerUnit: e.Qty, Unit: e.Unit, LeadTimeHours: e.LeadTimeHours, Source: source}
			_ = db.Where(domain.FormulaIngredients{IngredientID: e.IngredientID}).FirstOrCreate(&ing)
		} else {
			ing := domain.FormulaIngredients{IngredientID: e.IngredientID, FormulaID: e.FormulaID, ComponentType: domain.ComponentTypeProduct, ProductID: e.ProductIDComp, QuantityPerUnit: e.Qty, Unit: e.Unit, ScrapRate: e.ScrapRate, LeadTimeHours: e.LeadTimeHours, Source: source}
			_ = db.Where(domain.FormulaIngredients{IngredientID: e.IngredientID}).FirstOrCreate(&ing)
		}
	}
}

func seedMaterials(db *gorm.DB) {
	now := time.Now()
	// Stock levels increased to cover aggregate demand from all seed jobs for easier testing
	materials := []domain.InventoryMaterials{
		{MaterialID: "MAT-001", MaterialName: "Carbon Steel Bar Ø50mm", Unit: "kg", CurrentStock: 30000, MinStock: 200, StorageLocation: "Rack-A1", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-002", MaterialName: "Stainless Steel Sheet 2mm", Unit: "kg", CurrentStock: 2500, MinStock: 150, StorageLocation: "Rack-A2", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-003", MaterialName: "Alloy Steel Billet 4140", Unit: "kg", CurrentStock: 30000, MinStock: 300, StorageLocation: "Rack-A3", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-004", MaterialName: "Chrome Steel Rod Ø60mm", Unit: "kg", CurrentStock: 25000, MinStock: 100, StorageLocation: "Rack-B1", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-005", MaterialName: "Epoxy Coating Agent", Unit: "L", CurrentStock: 15000, MinStock: 50, StorageLocation: "Chem-01", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-006", MaterialName: "Cutting Oil (Premium)", Unit: "L", CurrentStock: 8000, MinStock: 100, StorageLocation: "Chem-02", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-007", MaterialName: "Chrome Plating Solution", Unit: "L", CurrentStock: 2000, MinStock: 80, StorageLocation: "Chem-03", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-008", MaterialName: "Aluminium Alloy A380", Unit: "kg", CurrentStock: 30000, MinStock: 400, StorageLocation: "Rack-C1", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-009", MaterialName: "Cast Iron EN-GJL-250", Unit: "kg", CurrentStock: 20000, MinStock: 250, StorageLocation: "Rack-C2", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-010", MaterialName: "M8 Hex Bolt (Box 500)", Unit: "pcs", CurrentStock: 60000, MinStock: 500, StorageLocation: "Bin-D1", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-011", MaterialName: "O-Ring Kit (Hydraulic)", Unit: "set", CurrentStock: 25000, MinStock: 30, StorageLocation: "Bin-D2", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-012", MaterialName: "Powder Coat (RAL 7016)", Unit: "kg", CurrentStock: 3000, MinStock: 40, StorageLocation: "Chem-04", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-013", MaterialName: "Bearing SKF 6205", Unit: "pcs", CurrentStock: 5000, MinStock: 50, StorageLocation: "Bin-E1", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-014", MaterialName: "Hydraulic Seal Set", Unit: "set", CurrentStock: 25000, MinStock: 20, StorageLocation: "Bin-E2", Status: domain.InventoryStatusInStock, LastUpdated: now},
	}
	for _, m := range materials {
		_ = db.Where(domain.InventoryMaterials{MaterialID: m.MaterialID}).FirstOrCreate(&m)
	}
}

func seedExpectedArrivals(db *gorm.DB) {
	now := time.Now()
	arrivals := []domain.InventoryExpectedArrival{
		{ArrivalID: "ARR-SEED-001", MaterialID: "MAT-007", Quantity: 200, ExpectedArriveAt: now.AddDate(0, 0, 7), Status: domain.ExpectedArrivalStatusPending, Notes: "Chrome plating solution - PO #4521", CreatedAt: now},
		{ArrivalID: "ARR-SEED-002", MaterialID: "MAT-002", Quantity: 100, ExpectedArriveAt: now.AddDate(0, 0, 14), Status: domain.ExpectedArrivalStatusPending, Notes: "Stainless sheet restock", CreatedAt: now},
		{ArrivalID: "ARR-SEED-003", MaterialID: "MAT-005", Quantity: 80, ExpectedArriveAt: now.AddDate(0, 0, 5), Status: domain.ExpectedArrivalStatusPending, Notes: "Epoxy coating - urgent", CreatedAt: now},
	}
	for _, a := range arrivals {
		_ = db.Where(domain.InventoryExpectedArrival{ArrivalID: a.ArrivalID}).FirstOrCreate(&a)
	}
}

func seedProductInventory(db *gorm.DB) {
	now := time.Now()
	items := []domain.ProductInventory{
		{InventoryID: "PINV-SEED-001", ProductID: "P-007", QuantityOnHand: 60, QuantityReserved: 12, Status: domain.ProductInventoryStatusAvailable, StorageLocation: "WIP-A1", AvailableFrom: now, LastUpdated: now},
		{InventoryID: "PINV-SEED-002", ProductID: "P-008", QuantityOnHand: 24, QuantityReserved: 8, Status: domain.ProductInventoryStatusAvailable, StorageLocation: "WIP-A2", AvailableFrom: now.Add(12 * time.Hour), LastUpdated: now},
		{InventoryID: "PINV-SEED-003", ProductID: "P-009", QuantityOnHand: 32, QuantityReserved: 4, Status: domain.ProductInventoryStatusAvailable, StorageLocation: "WIP-B1", AvailableFrom: now, LastUpdated: now},
	}
	for _, item := range items {
		_ = db.Where(domain.ProductInventory{InventoryID: item.InventoryID}).FirstOrCreate(&item)
	}
}

func seedInventoryReservations(db *gorm.DB) {
	now := time.Now()
	// Reduced reservations to avoid shortages; aligned with increased stock levels
	items := []domain.InventoryReservation{
		{ReservationID: "RES-SEED-001", MaterialID: "MAT-005", JobID: "JOB-SEED-001", ReservedQty: 100, NeededAt: now.Add(24 * time.Hour), Status: domain.InventoryReservationStatusPending, CreatedAt: now},
		{ReservationID: "RES-SEED-002", MaterialID: "MAT-007", JobID: "JOB-SEED-002", ReservedQty: 100, NeededAt: now.Add(48 * time.Hour), Status: domain.InventoryReservationStatusPending, CreatedAt: now},
		{ReservationID: "RES-SEED-003", MaterialID: "MAT-012", JobID: "JOB-SEED-003", ReservedQty: 50, NeededAt: now.Add(36 * time.Hour), Status: domain.InventoryReservationStatusPending, CreatedAt: now},
	}
	for _, item := range items {
		_ = db.Where(domain.InventoryReservation{ReservationID: item.ReservationID}).FirstOrCreate(&item)
	}
}

func seedBOM(db *gorm.DB) {
	// Derive ProductBOM from Formula (scheduler prefers Formula; ProductBOM kept in sync)
	_ = db.Exec("DELETE FROM product_bom WHERE product_id IN ('P-001','P-002','P-003','P-004','P-005','P-006','P-007','P-008','P-009')").Error
	formulaToProduct := map[string]string{"F-001": "P-001", "F-002": "P-002", "F-003": "P-003", "F-004": "P-004", "F-005": "P-005", "F-006": "P-006", "F-007": "P-007", "F-008": "P-008", "F-009": "P-009"}
	var ings []domain.FormulaIngredients
	_ = db.Where("formula_id LIKE 'F-0%'").Find(&ings)
	for _, i := range ings {
		productID := formulaToProduct[i.FormulaID]
		if productID == "" {
			continue
		}
		bomID := "BOM-" + strings.ReplaceAll(productID, "-", "") + "-" + strings.TrimPrefix(i.IngredientID, "ING-"+i.FormulaID+"-")
		if i.ComponentType == domain.ComponentTypeMaterial && i.MaterialID != nil {
			mat := *i.MaterialID
			var b domain.ProductBOM
			_ = db.Where(domain.ProductBOM{ProductID: productID, ComponentType: domain.ComponentTypeMaterial, MaterialID: &mat}).
				Attrs(domain.ProductBOM{BOMID: bomID, QuantityRequired: i.QuantityPerUnit, Unit: i.Unit}).
				FirstOrCreate(&b)
		} else if i.ComponentType == domain.ComponentTypeProduct && i.ProductID != nil {
			sub := *i.ProductID
			var b domain.ProductBOM
			_ = db.Where(domain.ProductBOM{ProductID: productID, ComponentType: domain.ComponentTypeProduct, ProductComponentID: &sub}).
				Attrs(domain.ProductBOM{BOMID: bomID, QuantityRequired: i.QuantityPerUnit, Unit: i.Unit}).
				FirstOrCreate(&b)
		}
	}
}

func seedProcessStepMaterials(db *gorm.DB) {
	_ = db.Exec("DELETE FROM process_step_materials WHERE step_id LIKE 'STP-P%'").Error
	for _, e := range bomSpec() {
		id := psmID(e.StepID, e.MaterialID, e.ProductIDComp, e.Role)
		m := domain.ProcessStepMaterial{
			ID:              id,
			StepID:          e.StepID,
			MaterialID:      e.MaterialID,
			ProductID:       e.ProductIDComp,
			Role:            e.Role,
			QuantityPerUnit: e.Qty,
			Unit:            e.Unit,
		}
		_ = db.Where(domain.ProcessStepMaterial{ID: id}).FirstOrCreate(&m)
	}
}

func psmID(stepID string, materialID, productID *string, role string) string {
	suffix := "OUT"
	if materialID != nil {
		suffix = *materialID
	} else if productID != nil {
		suffix = *productID
	}
	return "PSM-" + strings.TrimPrefix(stepID, "STP-") + "-" + strings.ReplaceAll(suffix, "-", "")
}

// validateBOMConsistency asserts Sum(ProcessStepMaterial input) == Formula per ingredient.
func validateBOMConsistency(db *gorm.DB) {
	formulaToProduct := map[string]string{"F-001": "P-001", "F-002": "P-002", "F-003": "P-003", "F-004": "P-004", "F-005": "P-005", "F-006": "P-006", "F-007": "P-007", "F-008": "P-008", "F-009": "P-009"}
	stepToProduct := func(stepID string) string {
		// STP-P001-1 -> P-001
		s := strings.TrimPrefix(stepID, "STP-")
		parts := strings.SplitN(s, "-", 2)
		if len(parts) < 2 {
			return ""
		}
		p := parts[0] // P001
		if len(p) >= 4 && p[0] == 'P' {
			return "P-" + p[1:]
		}
		return ""
	}

	var ings []domain.FormulaIngredients
	_ = db.Where("formula_id LIKE 'F-0%'").Find(&ings)
	var psms []domain.ProcessStepMaterial
	_ = db.Where("step_id LIKE 'STP-P%' AND role = ?", domain.ProcessStepMaterialRoleInput).Find(&psms)

	psmSum := map[string]float64{} // key: productID|materialID or productID|productID
	for _, p := range psms {
		prod := stepToProduct(p.StepID)
		if prod == "" {
			continue
		}
		var key string
		if p.MaterialID != nil {
			key = prod + "|M:" + *p.MaterialID
		} else if p.ProductID != nil {
			key = prod + "|P:" + *p.ProductID
		} else {
			continue
		}
		psmSum[key] += p.QuantityPerUnit
	}

	var fail bool
	for _, i := range ings {
		productID := formulaToProduct[i.FormulaID]
		if productID == "" {
			continue
		}
		var key string
		if i.MaterialID != nil {
			key = productID + "|M:" + *i.MaterialID
		} else if i.ProductID != nil {
			key = productID + "|P:" + *i.ProductID
		} else {
			continue
		}
		sum := psmSum[key]
		if sum != i.QuantityPerUnit {
			log.Printf("  BOM consistency FAIL: %s ingredient %s: Formula=%.4g, ProcessStepMaterial sum=%.4g", productID, key, i.QuantityPerUnit, sum)
			fail = true
		}
	}
	if fail {
		log.Fatal("BOM consistency validation failed")
	}
}

func seedJobs(db *gorm.DB) map[string][]string {
	jobRepo := repository.NewJobRepository(db)
	stepRepo := repository.NewJobStepRepository(db)
	slotRepo := repository.NewJobSlotRepository(db)
	processRepo := repository.NewProcessRepository(db)
	productRepo := repository.NewProductRepository(db)

	// Keep seed reruns idempotent: delete seed-owned jobs and descendants (including AI proposals).
	_ = db.Exec(`DELETE FROM ai_proposals WHERE job_id IN (SELECT job_id FROM jobs WHERE notes LIKE 'seed:%')`).Error
	_ = db.Exec(`DELETE FROM quality_inspection_records 
		WHERE job_step_id IN (
			SELECT js.job_step_id FROM job_steps js
			JOIN jobs j ON j.job_id = js.job_id WHERE j.notes LIKE 'seed:%'
		)`).Error
	_ = db.Exec(`DELETE FROM production_logs
		WHERE slot_id IN (
			SELECT s.slot_id FROM job_step_schedule_slots s
			JOIN job_steps js ON js.job_step_id = s.job_step_id
			JOIN jobs j ON j.job_id = js.job_id WHERE j.notes LIKE 'seed:%'
		)`).Error
	_ = db.Exec(`DELETE FROM job_step_schedule_slots WHERE job_step_id IN (
			SELECT js.job_step_id FROM job_steps js JOIN jobs j ON j.job_id = js.job_id WHERE j.notes LIKE 'seed:%'
		)`).Error
	_ = db.Exec(`DELETE FROM job_steps WHERE job_id IN (SELECT job_id FROM jobs WHERE notes LIKE 'seed:%')`).Error
	_ = db.Exec(`DELETE FROM jobs WHERE notes LIKE 'seed:%'`).Error

	jobSlots := map[string][]string{}
	seedBaseDate := time.Now().UTC().Truncate(24 * time.Hour)
	deadlineFor := func(days int) time.Time {
		return seedBaseDate.Add(time.Duration(days) * 24 * time.Hour)
	}
	// Jobs use deadlines relative to today (14 or 21 days ahead). Unscheduled; schedule via POST /ai/scheduling/batch-proposals.
	// Medium-load quantities to keep seed realistic and schedulable while still exercising fallback logic.
	// Extra jobs (013–018) added to increase contention.
	specs := []struct {
		jobID        string
		productID    string
		priority     string
		deadlineDays int
		status       string
		qty          int
		slotSpecs    []struct {
			machineID, start  string
			durationMins, qty int
		}
	}{
		{"JOB-SEED-001", "P-001", "high", 14, domain.JobStatusPlanned, 1600, nil},
		{"JOB-SEED-002", "P-002", "medium", 14, domain.JobStatusPlanned, 900, nil},
		{"JOB-SEED-003", "P-003", "high", 14, domain.JobStatusPlanned, 1200, nil},
		{"JOB-SEED-004", "P-004", "medium", 21, domain.JobStatusPlanned, 800, nil},
		{"JOB-SEED-005", "P-005", "low", 21, domain.JobStatusPlanned, 1800, nil},
		{"JOB-SEED-006", "P-006", "high", 14, domain.JobStatusPlanned, 500, nil},
		{"JOB-SEED-007", "P-001", "medium", 14, domain.JobStatusPlanned, 1100, nil},
		{"JOB-SEED-008", "P-002", "high", 14, domain.JobStatusPlanned, 1400, nil},
		{"JOB-SEED-009", "P-003", "low", 21, domain.JobStatusPlanned, 900, nil},
		{"JOB-SEED-010", "P-004", "medium", 21, domain.JobStatusPlanned, 700, nil},
		{"JOB-SEED-011", "P-008", "high", 14, domain.JobStatusPlanned, 800, nil},
		{"JOB-SEED-012", "P-009", "low", 21, domain.JobStatusPlanned, 900, nil},
		{"JOB-SEED-013", "P-001", "high", 14, domain.JobStatusPlanned, 1000, nil},
		{"JOB-SEED-014", "P-002", "medium", 14, domain.JobStatusPlanned, 850, nil},
		{"JOB-SEED-015", "P-005", "high", 14, domain.JobStatusPlanned, 1400, nil},
		{"JOB-SEED-016", "P-006", "medium", 21, domain.JobStatusPlanned, 600, nil},
		{"JOB-SEED-017", "P-004", "low", 21, domain.JobStatusPlanned, 900, nil},
		{"JOB-SEED-018", "P-008", "medium", 14, domain.JobStatusPlanned, 900, nil},
	}

	now := time.Now()
	for _, spec := range specs {
		prod, err := productRepo.GetByID(spec.productID)
		if err != nil || prod == nil {
			log.Printf("  skip job %s: product %s not found", spec.jobID, spec.productID)
			continue
		}
		proc, err := processRepo.GetProcessByProductID(spec.productID)
		if err != nil || proc == nil {
			log.Printf("  skip job %s: process not found", spec.jobID)
			continue
		}
		pSteps, err := processRepo.ListStepsByProcessID(proc.ProcessID)
		if err != nil || len(pSteps) == 0 {
			log.Printf("  skip job %s: process steps not found", spec.jobID)
			continue
		}
		if len(spec.slotSpecs) > 0 && len(pSteps) < len(spec.slotSpecs) {
			log.Printf("  skip job %s: process steps mismatch", spec.jobID)
			continue
		}

		deadline := deadlineFor(spec.deadlineDays)
		deadlineStr := deadline.Format(time.RFC3339)
		job := &domain.Job{
			JobID:             spec.jobID,
			ProductID:         spec.productID,
			QuantityTotal:     spec.qty,
			QuantityCompleted: 0,
			Priority:          spec.priority,
			Deadline:          deadline,
			Status:            spec.status,
			CreatedAt:         now,
			UpdatedAt:         now,
			Notes:             fmt.Sprintf("seed:%s:%s:%d", spec.productID, deadlineStr, spec.qty),
		}
		if err := jobRepo.Create(job); err != nil {
			log.Printf("  job %s: %v", spec.jobID, err)
			continue
		}

		stepCount := len(spec.slotSpecs)
		if stepCount == 0 {
			stepCount = len(pSteps)
		}
		jobSteps := make([]domain.JobSteps, 0, stepCount)
		for i := 0; i < stepCount; i++ {
			jsID := fmt.Sprintf("JS-SEED-%s-%d", strings.TrimPrefix(spec.jobID, "JOB-SEED-"), i+1)
			status := domain.JobStepStatusScheduled
			if len(spec.slotSpecs) == 0 {
				status = domain.JobStepStatusPending
			}
			jobSteps = append(jobSteps, domain.JobSteps{
				JobStepID:         jsID,
				JobID:             spec.jobID,
				StepID:            pSteps[i].StepID,
				StepSequence:      i + 1,
				QuantityTarget:    spec.qty,
				QuantityCompleted: 0,
				Status:            status,
			})
		}
		if err := stepRepo.CreateBatch(jobSteps); err != nil {
			log.Printf("  job %s steps: %v", spec.jobID, err)
			continue
		}

		slotIDs := make([]string, 0, len(spec.slotSpecs))
		for i, ss := range spec.slotSpecs {
			slotID := fmt.Sprintf("SLOT-SEED-%s-%d", strings.TrimPrefix(spec.jobID, "JOB-SEED-"), i+1)
			start := parseTime(ss.start)
			end := start.Add(time.Duration(ss.durationMins) * time.Minute)
			slot := &domain.JobStepScheduleSlots{
				SlotID:            slotID,
				JobStepID:         jobSteps[i].JobStepID,
				MachineID:         ss.machineID,
				ScheduledStart:    start,
				ScheduledEnd:      end,
				QuantityPlanned:   ss.qty,
				SplitGroupID:      "SG-" + jobSteps[i].JobStepID,
				AllocationPercent: 100,
				Status:            domain.SlotStatusPlanned,
			}
			if err := slotRepo.Create(slot); err != nil {
				log.Printf("  slot %s: %v", slotID, err)
				continue
			}
			slotIDs = append(slotIDs, slotID)
		}
		jobSlots[spec.jobID] = slotIDs
	}
	return jobSlots
}

func seedAIProposals(db *gorm.DB, jobSlots map[string][]string) {
	proposalRepo := repository.NewAIProposalRepository(db)
	stepRepo := repository.NewJobStepRepository(db)
	slotRepo := repository.NewJobSlotRepository(db)

	jobID := "JOB-SEED-001"
	slotIDs, ok := jobSlots[jobID]
	if !ok || len(slotIDs) == 0 {
		return
	}

	// Build proposed slots from existing slots for JOB-SEED-001
	type proposedSlot struct {
		JobStepID             string    `json:"job_step_id"`
		StepID                string    `json:"step_id"`
		StepName              string    `json:"step_name"`
		MachineID             string    `json:"machine_id"`
		MachineName           string    `json:"machine_name"`
		ScheduledStart        time.Time `json:"scheduled_start"`
		ScheduledEnd          time.Time `json:"scheduled_end"`
		QuantityPlanned       int       `json:"quantity_planned"`
		AllocationPercent     float64   `json:"allocation_percent"`
		IsParallel            bool      `json:"is_parallel"`
		BatchSequence         int       `json:"batch_sequence"`
		EstimatedDurationMins int       `json:"estimated_duration_mins"`
		Reasoning             []string  `json:"reasoning"`
	}
	type schedulingProposal struct {
		ProposalID     string         `json:"proposal_id"`
		JobID          string         `json:"job_id"`
		ProductID      string         `json:"product_id"`
		Version        int            `json:"version"`
		Status         string         `json:"status"`
		Engine         string         `json:"engine"`
		EngineVersion  string         `json:"engine_version"`
		ObjectiveScore float64        `json:"objective_score"`
		GeneratedAt    time.Time      `json:"generated_at"`
		Feasible       bool           `json:"feasible"`
		ProposedSlots  []proposedSlot `json:"proposed_slots"`
	}

	var slots []proposedSlot
	for _, slotID := range slotIDs {
		s, err := slotRepo.GetByID(slotID)
		if err != nil || s == nil {
			continue
		}
		dur := int(s.ScheduledEnd.Sub(s.ScheduledStart).Minutes())
		if dur <= 0 {
			dur = 60
		}
		slots = append(slots, proposedSlot{
			JobStepID:             s.JobStepID,
			StepID:                "",
			StepName:              "",
			MachineID:             s.MachineID,
			MachineName:           s.MachineID,
			ScheduledStart:        s.ScheduledStart,
			ScheduledEnd:          s.ScheduledEnd,
			QuantityPlanned:       s.QuantityPlanned,
			AllocationPercent:     100,
			EstimatedDurationMins: dur,
			Reasoning:             []string{"Seed proposal for chatbot testing."},
		})
	}

	stepList, _ := stepRepo.ListByJobID(jobID)
	for i := range slots {
		if i < len(stepList) {
			slots[i].StepID = stepList[i].StepID
		}
	}

	now := time.Now()
	prop := schedulingProposal{
		ProposalID:     "AIPROP-SEED-001",
		JobID:          jobID,
		ProductID:      "P-001",
		Version:        1,
		Status:         domain.AIProposalStatusDraft,
		Engine:         "heuristic",
		EngineVersion:  "1.0",
		ObjectiveScore: 850,
		GeneratedAt:    now,
		Feasible:       true,
		ProposedSlots:  slots,
	}
	propJSON, _ := json.Marshal(prop)

	record := &domain.AIProposal{
		ProposalID:     "AIPROP-SEED-001",
		JobID:          jobID,
		Version:        1,
		Status:         domain.AIProposalStatusDraft,
		Engine:         "heuristic",
		EngineVersion:  "1.0",
		ObjectiveScore: 850,
		InputHash:      "seed-hash-001",
		SummaryText:    "Draft proposal for JOB-SEED-001 (Valve Body Assembly) - use for approve/reject/apply chatbot tests.",
		ProposalJSON:   string(propJSON),
		GeneratedBy:    "seed",
		GeneratedAt:    now,
		CreatedAt:      now,
		UpdatedAt:      now,
	}
	_ = proposalRepo.Create(record)
}

func seedProductionLogs(db *gorm.DB, jobSlots map[string][]string) {
	plRepo := repository.NewProductionLogRepository(db)
	var count int
	for _, slots := range jobSlots {
		if count >= 5 {
			break
		}
		if len(slots) == 0 {
			continue
		}
		start := parseTime("2026-01-06T08:00:00Z")
		end := start.Add(2 * time.Hour)
		pl := domain.ProductionLogs{
			ProductionID:     id.NewPrefixed("PL-"),
			SlotID:           slots[0],
			StartTime:        start,
			EndTime:          end,
			QuantityProduced: 100,
			QuantityScrap:    2,
			OperatorNotes:    "Seed data",
		}
		if err := plRepo.Create(&pl); err != nil {
			log.Printf("  prod log: %v", err)
		} else {
			count++
		}
	}
}

func seedQuality(db *gorm.DB, jobSlots map[string][]string) {
	qcRepo := repository.NewQualityRepository(db)
	slotRepo := repository.NewJobSlotRepository(db)
	var count int
	for _, slots := range jobSlots {
		if count >= 3 {
			break
		}
		if len(slots) == 0 {
			continue
		}
		slot, _ := slotRepo.GetByID(slots[0])
		if slot == nil {
			continue
		}
		r := domain.QualityInspectionRecords{
			InspectionID:   id.NewPrefixed("QC-"),
			JobStepID:      slot.JobStepID,
			InspectionTime: time.Now(),
			Result:         domain.QualityResultPass,
			DefectCount:    0,
		}
		if err := qcRepo.Create(&r); err != nil {
			log.Printf("  quality: %v", err)
		} else {
			count++
		}
	}
}

func seedMaintenance(db *gorm.DB) {
	mntRepo := repository.NewMaintenanceRepository(db)
	downtimeRepo := repository.NewMachineDowntimeRepository(db)

	maints := []domain.MaintenanceRecords{
		{MaintenanceID: id.NewPrefixed("MNT-"), MachineID: "M-CTG-01", MaintenanceType: "preventive", Technician: "Ahmad Zaki", StartTime: parseTime("2026-01-05T08:00:00Z"), EndTime: parseTime("2026-01-05T16:00:00Z"), Description: "Replaced spray nozzles, recalibrated temperature controller."},
		{MaintenanceID: id.NewPrefixed("MNT-"), MachineID: "M-LTH-02", MaintenanceType: "preventive", Technician: "Lee Wei Hao", StartTime: parseTime("2026-01-06T06:00:00Z"), EndTime: parseTime("2026-01-06T08:00:00Z"), Description: "Spindle bearing lubrication, chuck jaw replacement"},
		{MaintenanceID: id.NewPrefixed("MNT-"), MachineID: "M-CNC-01", MaintenanceType: "preventive", Technician: "Rajan Kumar", StartTime: parseTime("2026-01-05T07:00:00Z"), EndTime: parseTime("2026-01-05T11:00:00Z"), Description: "Tool magazine cleaned, ATC arm calibrated"},
	}
	for _, m := range maints {
		_ = mntRepo.Create(&m)
	}
	downtimes := []domain.MachineDowntime{
		{DowntimeID: id.NewPrefixed("DT-"), MachineID: "M-CNC-01", Cause: "Coolant pump low pressure alarm", StartTime: parseTime("2026-01-06T09:00:00Z"), EndTime: parseTime("2026-01-06T09:10:00Z"), DurationMinutes: 10},
		{DowntimeID: id.NewPrefixed("DT-"), MachineID: "M-CTG-01", Cause: "Coating solution temperature out of range", StartTime: parseTime("2026-01-07T10:30:00Z"), EndTime: parseTime("2026-01-07T10:45:00Z"), DurationMinutes: 15},
	}
	for _, d := range downtimes {
		_ = downtimeRepo.Create(&d)
	}
}

func seedReferenceData(db *gorm.DB) {
	// Machine types
	machineTypes := []domain.ReferenceMachineType{
		{Name: "CNC Mill", Description: "3-axis / 5-axis milling centres"},
		{Name: "CNC Lathe", Description: "Turning centres"},
		{Name: "3D Printer", Description: "FDM / SLA additive manufacturing"},
		{Name: "Welding Robot", Description: "Automated arc / MIG / TIG welders"},
		{Name: "Stamping Press", Description: "Metal forming press"},
		{Name: "Hydraulic Press", Description: "Hydraulic forming / punching press"},
		{Name: "Laser Cutter", Description: "CO₂ / fibre laser cutting"},
		{Name: "Laser Welder", Description: "Precision laser welding"},
		{Name: "Assembly Robot", Description: "Pick-and-place / SCARA robot"},
		{Name: "Assembly Station", Description: "Manual or semi-automated assembly bench"},
		{Name: "Coating Station", Description: "Spray / powder coating booth"},
		{Name: "Painting Station", Description: "Automated painting line"},
		{Name: "Heat Treatment Unit", Description: "Furnace / oven / annealing unit"},
		{Name: "Quality Control Station", Description: "CMM / vision inspection station"},
		{Name: "Conveyor System", Description: "Material transport conveyor"},
		{Name: "Grinding Machine", Description: "Surface / cylindrical grinder"},
		{Name: "Drilling Machine", Description: "Radial / column drill press"},
		{Name: "Milling Machine", Description: "Conventional milling machine"},
		{Name: "CNC Milling", Description: "CNC milling centres"},
		{Name: "Turning", Description: "Lathe turning centres"},
		{Name: "Surface Coating", Description: "Spray / powder coating"},
		{Name: "Assembly", Description: "Assembly workstations"},
		{Name: "Inspection", Description: "Quality inspection stations"},
		{Name: "Pressing", Description: "Press operations"},
	}
	for _, m := range machineTypes {
		var rec domain.ReferenceMachineType
		_ = db.FirstOrCreate(&rec, m)
	}

	// Product types
	productTypes := []string{
		"Hydraulic Components", "Mechanical Parts", "Electronic Components",
		"Assembly / Sub-assembly", "Raw Material", "Finished Goods",
		"Consumables", "Chemical / Fluid", "Tooling & Fixtures", "Packaging Material",
		"Power Transmission", "Electrical Enclosures", "Structural Parts", "Fluid Handling",
	}
	for _, n := range productTypes {
		_ = db.FirstOrCreate(&domain.ReferenceProductType{Name: n}, domain.ReferenceProductType{Name: n})
	}

	// Factory locations (zone, bay)
	locations := []struct {
		zone string
		bay  *string
	}{
		{"Floor A", strPtr("Bay 1")}, {"Floor A", strPtr("Bay 2")}, {"Floor A", strPtr("Bay 3")},
		{"Floor B", strPtr("Bay 1")}, {"Floor B", strPtr("Bay 2")}, {"Floor B", strPtr("Bay 3")},
		{"Floor C", strPtr("Bay 1")}, {"Floor C", strPtr("Bay 2")},
		{"Maintenance Bay", nil}, {"Quality Lab", nil}, {"Paint Shop", nil},
		{"Warehouse Area", nil}, {"Loading Dock", nil}, {"Clean Room", nil},
		{"Bay A", strPtr("Bay 1")}, {"Bay A", strPtr("Bay 2")}, {"Bay B", strPtr("Bay 1")},
		{"Bay B", strPtr("Bay 2")}, {"Bay C", strPtr("Bay 1")}, {"Bay D", strPtr("Bay 1")},
		{"Bay E", strPtr("Bay 1")}, {"Bay F", strPtr("Bay 1")},
	}
	for _, loc := range locations {
		item := domain.ReferenceLocation{Zone: loc.zone, Bay: loc.bay}
		if loc.bay == nil {
			_ = db.Where("zone = ? AND bay IS NULL", loc.zone).FirstOrCreate(&item)
		} else {
			_ = db.Where("zone = ? AND bay = ?", loc.zone, *loc.bay).FirstOrCreate(&item)
		}
	}

	// Storage locations
	storageLocs := []struct {
		name string
		typ  string
	}{
		{"Warehouse A – Shelf 1", "shelf"}, {"Warehouse A – Shelf 2", "shelf"}, {"Warehouse A – Shelf 3", "shelf"},
		{"Warehouse B – Shelf 1", "shelf"}, {"Warehouse B – Shelf 2", "shelf"},
		{"Rack-A1", "rack"}, {"Rack-A2", "rack"}, {"Rack-A3", "rack"},
		{"Rack-B1", "rack"}, {"Rack-B2", "rack"}, {"Rack-B3", "rack"},
		{"Rack-C1", "rack"}, {"Rack-C2", "rack"},
		{"Cold Storage", "cold"}, {"Hazardous Storage", "hazardous"},
		{"Floor Storage", "floor"}, {"Receiving Dock", "dock"}, {"Shipping Dock", "dock"},
		{"Bin-D1", "shelf"}, {"Bin-D2", "shelf"}, {"Bin-E1", "shelf"}, {"Bin-E2", "shelf"},
		{"Chem-01", "hazardous"}, {"Chem-02", "hazardous"}, {"Chem-03", "hazardous"}, {"Chem-04", "hazardous"},
	}
	for _, s := range storageLocs {
		_ = db.FirstOrCreate(&domain.ReferenceStorageLocation{Name: s.name, Type: s.typ}, domain.ReferenceStorageLocation{Name: s.name})
	}

	// Step types
	stepTypes := []struct {
		name   string
		machTy *string
	}{
		{"Raw Material Preparation", nil},
		{"CNC Machining", strPtr("CNC Mill")},
		{"Turning / Lathing", strPtr("CNC Lathe")},
		{"Milling", strPtr("Milling Machine")},
		{"Drilling", strPtr("Drilling Machine")},
		{"Grinding / Polishing", strPtr("Grinding Machine")},
		{"Heat Treatment", strPtr("Heat Treatment Unit")},
		{"Surface Coating", strPtr("Coating Station")},
		{"Welding", strPtr("Welding Robot")},
		{"Assembly", strPtr("Assembly Station")},
		{"Sub-Assembly", strPtr("Assembly Station")},
		{"Quality Inspection", strPtr("Quality Control Station")},
		{"Packaging", nil},
		{"CNC Rough Milling", strPtr("CNC Mill")},
		{"CNC Finish Milling", strPtr("CNC Mill")},
		{"Turning – Bore", strPtr("CNC Lathe")},
		{"Final Assembly & Test", strPtr("Assembly Station")},
		{"Gear Blank Turning", strPtr("CNC Lathe")},
		{"Hobbing / CNC Mill", strPtr("CNC Mill")},
		{"Gear Inspection", strPtr("Quality Control Station")},
		{"Bar Turning", strPtr("CNC Lathe")},
		{"Chrome Plating", strPtr("Coating Station")},
		{"Final Inspection", strPtr("Quality Control Station")},
		{"Rough Boring", strPtr("CNC Mill")},
		{"Drilling & Tapping", strPtr("CNC Mill")},
		{"Powder Coating", strPtr("Coating Station")},
		{"Assembly & QC", strPtr("Assembly Station")},
		{"Stamping", strPtr("Stamping Press")},
		{"Casting", strPtr("Hydraulic Press")},
		{"Kit Assembly", strPtr("Assembly Station")},
		{"QC Inspection", strPtr("Quality Control Station")},
		{"Precision Turning", strPtr("CNC Lathe")},
		{"Grinding & Honing", strPtr("Grinding Machine")},
		{"Inspection", strPtr("Quality Control Station")},
		{"Gasket Cutting", strPtr("Assembly Station")},
		{"Kit Assembly & QC", strPtr("Quality Control Station")},
	}
	for _, st := range stepTypes {
		item := domain.ReferenceStepType{Name: st.name, DefaultMachineType: st.machTy}
		_ = db.FirstOrCreate(&item, domain.ReferenceStepType{Name: st.name})
	}
}

func strPtr(s string) *string {
	return &s
}

func ptr(t time.Time) *time.Time {
	return &t
}

func parseDate(s string) time.Time {
	t, _ := time.Parse("2006-01-02", s)
	return t
}

func parseTime(s string) time.Time {
	t, _ := time.Parse(time.RFC3339, s)
	return t
}
