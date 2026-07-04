// Seed command populates MySQL with mock data from MOCK_DATA_SEED.md
package seeddata

import (
	"emas/internal/domain"
	"emas/internal/repository"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"emas/pkg/id"
	"emas/pkg/productionexec"
	"gorm.io/gorm"
)

type SeedOptions struct {
	Migrate             bool
	ValidateFingerprint bool
}

func SeedCanonical(db *gorm.DB, opts SeedOptions) error {
	if db == nil {
		return fmt.Errorf("seed canonical: db is nil")
	}
	if opts.Migrate {
		if err := repository.AutoMigrate(db); err != nil {
			return fmt.Errorf("migrate: %w", err)
		}
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

	log.Println("Seeding completed report production history...")
	reportSlots := seedReportProductionHistory(db)

	log.Println("Seeding quality inspections...")
	seedQuality(db, reportSlots)

	log.Println("Seeding maintenance and downtime...")
	seedMaintenance(db)

	log.Println("Seeding scheduling settings (work template)...")
	seedSchedulingSettings(db)

	if opts.ValidateFingerprint {
		if err := AssertCanonicalFingerprint(db); err != nil {
			return err
		}
	}

	log.Println("Seed completed.")
	return nil
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
	_ = settingsRepo.PutInt("scheduling.subproduct.max_dependency_depth", 4)
	_ = settingsRepo.PutInt("scheduling.subproduct.max_generated_subjobs_per_root", 12)
	_ = settingsRepo.PutInt("scheduling.subproduct.max_total_generated_nodes_per_batch", 64)
	// Demo seeds should prefer "late but still schedulable" over failing early when
	// child subjobs push a parent suffix multiple times.
	_ = settingsRepo.PutInt("scheduling.subproduct.max_parent_reflow_passes_per_root", 12)
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
	// Drop and re-seed resource calendars so changes to hours/coverage take effect.
	_ = db.Exec("DELETE FROM resource_calendar WHERE id LIKE 'RC-RES-OP-%'").Error
	// ResourceCalendar: available 08:00–20:00 every day for 90 days.
	// Extended to 20:00 (12-hour shift) so large topup batches (up to ~2880 units
	// at standard throughput) fit within a single shift window.
	// Covers all 7 days so no weekday gap hits the 85-day apply-time scan.
	base := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location())
	for i := 0; i < 90; i++ {
		day := base.AddDate(0, 0, i)
		start := time.Date(day.Year(), day.Month(), day.Day(), 8, 0, 0, 0, day.Location())
		end := time.Date(day.Year(), day.Month(), day.Day(), 20, 0, 0, 0, day.Location())
		for _, res := range resources {
			id := fmt.Sprintf("RC-%s-%d", res.ResourceID, i)
			cal := domain.ResourceCalendar{ID: id, ResourceID: res.ResourceID, StartTime: start, EndTime: end, AvailabilityType: "work"}
			_ = db.Where(domain.ResourceCalendar{ID: id}).FirstOrCreate(&cal)
		}
	}
}

func seedWIPInventory(db *gorm.DB) {
	_ = db.Exec("DELETE FROM wip_inventory WHERE id LIKE 'WIP-SEED-%'").Error
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
	// Keep deterministic shortage scenarios for recommendation testing:
	// - MAT-002 and MAT-010 are intentionally constrained.
	// - We upsert with Assign so rerunning seed always resets to these values.
	materials := []domain.InventoryMaterials{
		{MaterialID: "MAT-001", MaterialName: "Carbon Steel Bar Ø50mm", Unit: "kg", CurrentStock: 30000, MinStock: 200, StorageLocation: "Rack-A1", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-002", MaterialName: "Stainless Steel Sheet 2mm", Unit: "kg", CurrentStock: 300, MinStock: 150, StorageLocation: "Rack-A2", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-003", MaterialName: "Alloy Steel Billet 4140", Unit: "kg", CurrentStock: 30000, MinStock: 300, StorageLocation: "Rack-A3", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-004", MaterialName: "Chrome Steel Rod Ø60mm", Unit: "kg", CurrentStock: 25000, MinStock: 100, StorageLocation: "Rack-B1", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-005", MaterialName: "Epoxy Coating Agent", Unit: "L", CurrentStock: 15000, MinStock: 50, StorageLocation: "Chem-01", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-006", MaterialName: "Cutting Oil (Premium)", Unit: "L", CurrentStock: 8000, MinStock: 100, StorageLocation: "Chem-02", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-007", MaterialName: "Chrome Plating Solution", Unit: "L", CurrentStock: 2000, MinStock: 80, StorageLocation: "Chem-03", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-008", MaterialName: "Aluminium Alloy A380", Unit: "kg", CurrentStock: 30000, MinStock: 400, StorageLocation: "Rack-C1", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-009", MaterialName: "Cast Iron EN-GJL-250", Unit: "kg", CurrentStock: 20000, MinStock: 250, StorageLocation: "Rack-C2", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-010", MaterialName: "M8 Hex Bolt (Box 500)", Unit: "pcs", CurrentStock: 9000, MinStock: 500, StorageLocation: "Bin-D1", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-011", MaterialName: "O-Ring Kit (Hydraulic)", Unit: "set", CurrentStock: 25000, MinStock: 30, StorageLocation: "Bin-D2", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-012", MaterialName: "Powder Coat (RAL 7016)", Unit: "kg", CurrentStock: 3000, MinStock: 40, StorageLocation: "Chem-04", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-013", MaterialName: "Bearing SKF 6205", Unit: "pcs", CurrentStock: 5000, MinStock: 50, StorageLocation: "Bin-E1", Status: domain.InventoryStatusInStock, LastUpdated: now},
		{MaterialID: "MAT-014", MaterialName: "Hydraulic Seal Set", Unit: "set", CurrentStock: 25000, MinStock: 20, StorageLocation: "Bin-E2", Status: domain.InventoryStatusInStock, LastUpdated: now},
	}
	for _, m := range materials {
		_ = db.Where("material_id = ?", m.MaterialID).Assign(m).FirstOrCreate(&domain.InventoryMaterials{})
	}
}

func seedExpectedArrivals(db *gorm.DB) {
	now := time.Now()
	_ = db.Exec("DELETE FROM inventory_expected_arrivals WHERE arrival_id LIKE 'ARR-SEED-%'").Error
	arrivals := []domain.InventoryExpectedArrival{
		{ArrivalID: "ARR-SEED-001", MaterialID: "MAT-007", Quantity: 200, ExpectedArriveAt: now.AddDate(0, 0, 7), Status: domain.ExpectedArrivalStatusPending, Notes: "Chrome plating solution - PO #4521", CreatedAt: now},
		{ArrivalID: "ARR-SEED-002", MaterialID: "MAT-002", Quantity: 100, ExpectedArriveAt: now.AddDate(0, 0, 14), Status: domain.ExpectedArrivalStatusPending, Notes: "Stainless sheet restock", CreatedAt: now},
		{ArrivalID: "ARR-SEED-003", MaterialID: "MAT-005", Quantity: 80, ExpectedArriveAt: now.AddDate(0, 0, 5), Status: domain.ExpectedArrivalStatusPending, Notes: "Epoxy coating - urgent", CreatedAt: now},
		// M8 Hex Bolts (MAT-010) are consumed heavily by P-007 child-job production (8 pcs/unit).
		// Multiple jobs each spawn 3-5 child jobs producing P-007, exhausting the 60k stock.
		// These arrivals arrive before the job execution window (April 13+) and are counted
		// as available stock by materialAvailabilityForPlanning's pre-at arrival logic.
		{ArrivalID: "ARR-SEED-004", MaterialID: "MAT-010", Quantity: 12000, ExpectedArriveAt: now.AddDate(0, 0, 35), Status: domain.ExpectedArrivalStatusPending, Notes: "M8 Hex Bolt restock - delayed PO #5100", CreatedAt: now},
		{ArrivalID: "ARR-SEED-005", MaterialID: "MAT-010", Quantity: 12000, ExpectedArriveAt: now.AddDate(0, 0, 50), Status: domain.ExpectedArrivalStatusPending, Notes: "M8 Hex Bolt restock - delayed PO #5101", CreatedAt: now},
		// Stainless Steel Sheet (MAT-002) is consumed by P-008 child jobs (0.5 kg/unit) and
		// P-001 parent steps (0.08 kg/unit). Large P-008 child-job quantities from JOB-SEED-001,
		// 007, 013 exhaust the 2500 kg stock before later proposals apply.
		{ArrivalID: "ARR-SEED-006", MaterialID: "MAT-002", Quantity: 1000, ExpectedArriveAt: now.AddDate(0, 0, 40), Status: domain.ExpectedArrivalStatusPending, Notes: "Stainless Steel Sheet restock - delayed PO #5102", CreatedAt: now},
		// Stress-batch arrivals (for jobs 019–026):
		// New P-001/P-004 jobs generate additional P-007 child jobs (8 MAT-010/unit each).
		// Four extra P-001/P-004 jobs with ~350-420 units apiece push total MAT-010 demand
		// well beyond the 140k (60k stock + 80k from ARR-004/005) already earmarked for jobs 001–018.
		{ArrivalID: "ARR-SEED-007", MaterialID: "MAT-010", Quantity: 20000, ExpectedArriveAt: now.AddDate(0, 0, 65), Status: domain.ExpectedArrivalStatusPending, Notes: "M8 Hex Bolt restock - delayed PO #5103 (stress batch)", CreatedAt: now},
		{ArrivalID: "ARR-SEED-008", MaterialID: "MAT-010", Quantity: 20000, ExpectedArriveAt: now.AddDate(0, 0, 80), Status: domain.ExpectedArrivalStatusPending, Notes: "M8 Hex Bolt restock - delayed PO #5104 (stress batch buffer)", CreatedAt: now},
		// New P-001 jobs 019+022 generate additional P-008 child jobs (0.5 kg MAT-002/unit each).
		// Combined with JOB-SEED-026 direct P-008 production (580 units × 0.5 kg = 290 kg),
		// the extra demand from stress jobs requires an additional MAT-002 top-up.
		{ArrivalID: "ARR-SEED-009", MaterialID: "MAT-002", Quantity: 1500, ExpectedArriveAt: now.AddDate(0, 0, 70), Status: domain.ExpectedArrivalStatusPending, Notes: "Stainless Steel Sheet restock - delayed PO #5105 (stress batch)", CreatedAt: now},
	}
	for _, a := range arrivals {
		_ = db.Where(domain.InventoryExpectedArrival{ArrivalID: a.ArrivalID}).FirstOrCreate(&a)
	}
}

func seedProductInventory(db *gorm.DB) {
	now := time.Now()
	_ = db.Exec("DELETE FROM product_inventory WHERE inventory_id LIKE 'PINV-SEED-%'").Error
	items := []domain.ProductInventory{
		// Moderate shared buffers make the seed feel like a live shop floor instead
		// of an immediate shortage simulation on every subproduct.
		{InventoryID: "PINV-SEED-001", ProductID: "P-003", QuantityOnHand: 120, QuantityReserved: 20, Status: domain.ProductInventoryStatusAvailable, StorageLocation: "FG-B1", AvailableFrom: now, LastUpdated: now},
		{InventoryID: "PINV-SEED-002", ProductID: "P-007", QuantityOnHand: 90, QuantityReserved: 10, Status: domain.ProductInventoryStatusAvailable, StorageLocation: "FG-A1", AvailableFrom: now, LastUpdated: now},
		{InventoryID: "PINV-SEED-003", ProductID: "P-008", QuantityOnHand: 70, QuantityReserved: 8, Status: domain.ProductInventoryStatusAvailable, StorageLocation: "FG-A2", AvailableFrom: now, LastUpdated: now},
		{InventoryID: "PINV-SEED-004", ProductID: "P-009", QuantityOnHand: 80, QuantityReserved: 10, Status: domain.ProductInventoryStatusAvailable, StorageLocation: "FG-B2", AvailableFrom: now, LastUpdated: now},
	}
	for _, item := range items {
		_ = db.Where(domain.ProductInventory{InventoryID: item.InventoryID}).FirstOrCreate(&item)
	}
}

func seedInventoryReservations(db *gorm.DB) {
	now := time.Now()
	_ = db.Exec("DELETE FROM inventory_reservations WHERE reservation_id LIKE 'RES-SEED-%'").Error
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

	// Keep seed reruns idempotent: delete seed-owned jobs and scheduler-generated child jobs
	// that were created from seed proposals, plus their descendants and reservations.
	seedJobFilter := "notes LIKE 'seed:%' OR notes LIKE 'generated_by_scheduler:JOB-SEED-%'"
	_ = db.Exec(`DELETE FROM ai_proposals WHERE job_id IN (SELECT job_id FROM jobs WHERE ` + seedJobFilter + `)`).Error
	_ = db.Exec(`DELETE FROM quality_inspection_records 
		WHERE job_step_id IN (
			SELECT js.job_step_id FROM job_steps js
			JOIN jobs j ON j.job_id = js.job_id WHERE ` + seedJobFilter + `
		)`).Error
	_ = db.Exec(`DELETE FROM production_logs
		WHERE slot_id IN (
			SELECT s.slot_id FROM job_step_schedule_slots s
			JOIN job_steps js ON js.job_step_id = s.job_step_id
			JOIN jobs j ON j.job_id = js.job_id WHERE ` + seedJobFilter + `
		)`).Error
	_ = db.Exec(`DELETE FROM job_step_schedule_slots WHERE job_step_id IN (
			SELECT js.job_step_id FROM job_steps js JOIN jobs j ON j.job_id = js.job_id WHERE ` + seedJobFilter + `
		)`).Error
	_ = db.Exec(`DELETE FROM product_inventory_reservations WHERE job_id IN (SELECT job_id FROM jobs WHERE ` + seedJobFilter + `)`).Error
	_ = db.Exec(`DELETE FROM inventory_reservations WHERE job_id IN (SELECT job_id FROM jobs WHERE ` + seedJobFilter + `)`).Error
	// Clear planned production records written at apply time to bridge the plan-apply inventory gap.
	// These are safe to delete in full: status='planned' is only set by the scheduling apply flow.
	_ = db.Exec(`DELETE FROM product_inventory WHERE status = 'planned'`).Error
	_ = db.Exec(`DELETE FROM job_dependencies WHERE parent_job_id IN (SELECT job_id FROM jobs WHERE ` + seedJobFilter + `) OR child_job_id IN (SELECT job_id FROM jobs WHERE ` + seedJobFilter + `)`).Error
	_ = db.Exec(`DELETE FROM job_steps WHERE job_id IN (SELECT job_id FROM jobs WHERE ` + seedJobFilter + `)`).Error
	_ = db.Exec(`DELETE FROM jobs WHERE ` + seedJobFilter).Error

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
		{"JOB-SEED-001", "P-001", "high", 14, domain.JobStatusPlanned, 320, nil},
		{"JOB-SEED-002", "P-002", "medium", 14, domain.JobStatusPlanned, 420, nil},
		{"JOB-SEED-003", "P-003", "high", 14, domain.JobStatusPlanned, 180, nil},
		{"JOB-SEED-004", "P-004", "medium", 21, domain.JobStatusPlanned, 260, nil},
		{"JOB-SEED-005", "P-005", "low", 21, domain.JobStatusPlanned, 520, nil},
		{"JOB-SEED-006", "P-006", "high", 14, domain.JobStatusPlanned, 140, nil},
		{"JOB-SEED-007", "P-001", "medium", 14, domain.JobStatusPlanned, 220, nil},
		{"JOB-SEED-008", "P-002", "high", 14, domain.JobStatusPlanned, 360, nil},
		{"JOB-SEED-009", "P-003", "low", 21, domain.JobStatusPlanned, 140, nil},
		{"JOB-SEED-010", "P-004", "medium", 21, domain.JobStatusPlanned, 210, nil},
		{"JOB-SEED-011", "P-008", "high", 14, domain.JobStatusPlanned, 180, nil},
		{"JOB-SEED-012", "P-009", "low", 21, domain.JobStatusPlanned, 240, nil},
		{"JOB-SEED-013", "P-001", "high", 14, domain.JobStatusPlanned, 180, nil},
		{"JOB-SEED-014", "P-002", "medium", 14, domain.JobStatusPlanned, 260, nil},
		{"JOB-SEED-015", "P-005", "high", 14, domain.JobStatusPlanned, 380, nil},
		{"JOB-SEED-016", "P-006", "medium", 21, domain.JobStatusPlanned, 120, nil},
		{"JOB-SEED-017", "P-004", "low", 21, domain.JobStatusPlanned, 180, nil},
		{"JOB-SEED-018", "P-008", "medium", 14, domain.JobStatusPlanned, 160, nil},
		// Hard-scheduling stress batch (019–026):
		// Tight 8–11 day deadlines hit a machine schedule already packed by jobs 001–018.
		// Assembly machines (M-ASM-*) and CNC machines get overloaded, forcing the scheduler
		// to push completion PAST the deadline while remaining inside the 400-day horizon.
		// Expected outcome: Feasible=true, EstimatedCompletion > Deadline ("late but feasible").
		// Inventory is covered by arrivals ARR-SEED-007..009 added alongside these jobs.
		{"JOB-SEED-019", "P-001", "high", 9, domain.JobStatusPlanned, 400, nil},    // Valve Body; needs P-007+P-008 child jobs; very tight
		{"JOB-SEED-020", "P-004", "medium", 10, domain.JobStatusPlanned, 380, nil}, // Motor Housing; needs P-007 child jobs
		{"JOB-SEED-021", "P-006", "high", 9, domain.JobStatusPlanned, 200, nil},    // Pump Casing; needs P-003+P-009 child jobs
		{"JOB-SEED-022", "P-001", "medium", 8, domain.JobStatusPlanned, 300, nil},  // Valve Body; most aggressive deadline
		{"JOB-SEED-023", "P-004", "high", 11, domain.JobStatusPlanned, 420, nil},   // Motor Housing; borderline — may just make it
		{"JOB-SEED-024", "P-002", "low", 9, domain.JobStatusPlanned, 480, nil},     // Gear Set; simple BOM, pure machine-contention lateness
		{"JOB-SEED-025", "P-005", "medium", 8, domain.JobStatusPlanned, 680, nil},  // Control Bracket; heavy MAT-010 direct use
		{"JOB-SEED-026", "P-008", "high", 9, domain.JobStatusPlanned, 580, nil},    // Valve Spool; heavy MAT-002/MAT-004 use
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
		log.Printf("  seed proposal %s: no seed slots found; using job-step fallback slots", jobID)
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
	if len(slots) == 0 {
		base := time.Now().UTC().Add(24 * time.Hour).Truncate(time.Hour)
		for i, step := range stepList {
			start := base.Add(time.Duration(i*90) * time.Minute)
			end := start.Add(60 * time.Minute)
			slots = append(slots, proposedSlot{
				JobStepID:             step.JobStepID,
				StepID:                step.StepID,
				StepName:              step.StepID,
				MachineID:             "M-CNC-01",
				MachineName:           "CNC Mill 01",
				ScheduledStart:        start,
				ScheduledEnd:          end,
				QuantityPlanned:       step.QuantityTarget,
				AllocationPercent:     100,
				EstimatedDurationMins: 60,
				Reasoning:             []string{"Seed fallback proposal for approval/apply tests."},
			})
		}
	}
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

func SeedReportProductionHistory(db *gorm.DB, opts SeedOptions) error {
	if db == nil {
		return fmt.Errorf("seed report production history: db is nil")
	}
	if opts.Migrate {
		if err := repository.AutoMigrate(db); err != nil {
			return fmt.Errorf("migrate: %w", err)
		}
	}
	reportSlots, err := seedReportProductionHistoryStrict(db)
	if err != nil {
		return err
	}
	seedQuality(db, reportSlots)
	seedReportMaintenance(db)
	return nil
}

func seedReportProductionHistory(db *gorm.DB) map[string][]string {
	reportSlots, err := seedReportProductionHistoryStrict(db)
	if err != nil {
		log.Printf("  report production history: %v", err)
	}
	return reportSlots
}

func seedReportProductionHistoryStrict(db *gorm.DB) (map[string][]string, error) {
	reportSlots := map[string][]string{}
	err := db.Transaction(func(tx *gorm.DB) error {
		if err := clearReportProductionHistory(tx); err != nil {
			return err
		}
		base := time.Now().UTC().Truncate(24*time.Hour).AddDate(0, 0, -21)
		specs := []struct {
			ID       string
			Qty      int
			Scrap    int
			Day      int
			Priority string
		}{
			{ID: "001", Qty: 28, Scrap: 1, Day: 0, Priority: domain.JobPriorityMedium},
			{ID: "002", Qty: 36, Scrap: 0, Day: 4, Priority: domain.JobPriorityHigh},
			{ID: "003", Qty: 22, Scrap: 2, Day: 9, Priority: domain.JobPriorityLow},
			{ID: "004", Qty: 42, Scrap: 1, Day: 14, Priority: domain.JobPriorityMedium},
			{ID: "005", Qty: 30, Scrap: 0, Day: 18, Priority: domain.JobPriorityHigh},
		}
		for _, spec := range specs {
			start1 := base.AddDate(0, 0, spec.Day).Add(8 * time.Hour)
			end1 := start1.Add(45 * time.Minute)
			start2 := end1.Add(30 * time.Minute)
			end2 := start2.Add(60 * time.Minute)
			jobID := "JOB-RPT-" + spec.ID
			step1ID := "JS-RPT-" + spec.ID + "-1"
			step2ID := "JS-RPT-" + spec.ID + "-2"
			slot1ID := "SLOT-RPT-" + spec.ID + "-1"
			slot2ID := "SLOT-RPT-" + spec.ID + "-2"
			plannedInputUnits := spec.Qty + spec.Scrap

			if err := seedReportMaterialReceipts(tx, jobID, spec.ID, float64(plannedInputUnits), start1.Add(-2*time.Hour)); err != nil {
				return err
			}
			if err := tx.Create(&domain.Job{
				JobID:         jobID,
				ProductID:     "P-005",
				QuantityTotal: spec.Qty,
				Priority:      spec.Priority,
				Deadline:      end2.Add(24 * time.Hour),
				Status:        domain.JobStatusScheduled,
				CreatedAt:     start1.Add(-24 * time.Hour),
				UpdatedAt:     start1.Add(-24 * time.Hour),
				Notes:         fmt.Sprintf("seed-report:P-005:%s:%d", start1.Format(time.RFC3339), spec.Qty),
			}).Error; err != nil {
				return err
			}
			if err := tx.Create([]domain.JobSteps{
				{JobStepID: step1ID, JobID: jobID, StepID: "STP-P005-1", StepSequence: 1, QuantityTarget: spec.Qty, Status: domain.JobStepStatusScheduled},
				{JobStepID: step2ID, JobID: jobID, StepID: "STP-P005-2", StepSequence: 2, QuantityTarget: spec.Qty, Status: domain.JobStepStatusScheduled},
			}).Error; err != nil {
				return err
			}
			if err := tx.Create([]domain.JobStepScheduleSlots{
				{SlotID: slot1ID, JobStepID: step1ID, MachineID: "M-PRS-01", ScheduledStart: start1, ScheduledEnd: end1, QuantityPlanned: plannedInputUnits, SplitGroupID: "SG-" + step1ID, AllocationPercent: 100, Status: domain.SlotStatusPlanned},
				{SlotID: slot2ID, JobStepID: step2ID, MachineID: "M-CTG-01", ScheduledStart: start2, ScheduledEnd: end2, QuantityPlanned: spec.Qty, SplitGroupID: "SG-" + step2ID, AllocationPercent: 100, Status: domain.SlotStatusPlanned},
			}).Error; err != nil {
				return err
			}
			if err := seedReportLogProduction(tx, seedReportLogRequest{
				SlotID:           slot1ID,
				StartTime:        start1,
				EndTime:          end1,
				QuantityProduced: spec.Qty,
				QuantityScrap:    spec.Scrap,
				OperatorNotes:    "Historical report seed: stamping",
			}); err != nil {
				return err
			}
			if err := seedReportLogProduction(tx, seedReportLogRequest{
				SlotID:           slot2ID,
				StartTime:        start2,
				EndTime:          end2,
				QuantityProduced: spec.Qty,
				OperatorNotes:    "Historical report seed: coating",
			}); err != nil {
				return err
			}
			if spec.ID == "002" || spec.ID == "004" {
				if err := tx.Create(&domain.MachineDowntime{
					DowntimeID:      "DT-RPT-" + spec.ID,
					MachineID:       "M-CTG-01",
					JobStepSlotID:   slot2ID,
					Cause:           "Coating booth adjustment",
					StartTime:       start2.Add(15 * time.Minute),
					EndTime:         start2.Add(25 * time.Minute),
					DurationMinutes: 10,
				}).Error; err != nil {
					return err
				}
			}
			reportSlots[jobID] = []string{slot1ID, slot2ID}
		}
		return nil
	})
	return reportSlots, err
}

func clearReportProductionHistory(db *gorm.DB) error {
	reportJobFilter := "j.job_id LIKE 'JOB-RPT-%' OR j.notes LIKE 'seed-report:%'"
	rootJobFilter := "job_id LIKE 'JOB-RPT-%' OR notes LIKE 'seed-report:%'"
	statements := []string{
		`DELETE FROM quality_inspection_records WHERE job_step_id IN (
			SELECT js.job_step_id FROM job_steps js JOIN jobs j ON j.job_id = js.job_id WHERE ` + reportJobFilter + `
		)`,
		`DELETE FROM machine_downtime WHERE job_step_slot_id IN (
			SELECT s.slot_id FROM job_step_schedule_slots s
			JOIN job_steps js ON js.job_step_id = s.job_step_id
			JOIN jobs j ON j.job_id = js.job_id WHERE ` + reportJobFilter + `
		) OR downtime_id LIKE 'DT-RPT-%'`,
		`DELETE FROM production_logs WHERE slot_id IN (
			SELECT s.slot_id FROM job_step_schedule_slots s
			JOIN job_steps js ON js.job_step_id = s.job_step_id
			JOIN jobs j ON j.job_id = js.job_id WHERE ` + reportJobFilter + `
		)`,
		`DELETE FROM job_step_schedule_slots WHERE job_step_id IN (
			SELECT js.job_step_id FROM job_steps js JOIN jobs j ON j.job_id = js.job_id WHERE ` + reportJobFilter + `
		)`,
		`DELETE FROM inventory_transactions WHERE reference_job_id LIKE 'JOB-RPT-%' OR transaction_id LIKE 'TXN-RPT-%'`,
		`DELETE FROM product_inventory WHERE storage_location = 'FG-RPT'`,
		`DELETE FROM wip_inventory WHERE id LIKE 'WIP-RPT-%' OR job_step_id IN (
			SELECT js.job_step_id FROM job_steps js JOIN jobs j ON j.job_id = js.job_id WHERE ` + reportJobFilter + `
		)`,
		`DELETE FROM job_steps WHERE job_id IN (SELECT job_id FROM jobs WHERE ` + rootJobFilter + `)`,
		`DELETE FROM jobs WHERE ` + rootJobFilter,
	}
	for _, stmt := range statements {
		if err := db.Exec(stmt).Error; err != nil {
			return err
		}
	}
	return nil
}

func seedReportMaterialReceipts(db *gorm.DB, jobID, suffix string, units float64, ts time.Time) error {
	receipts := []struct {
		MaterialID string
		Qty        float64
	}{
		{MaterialID: "MAT-008", Qty: 1.2 * units},
		{MaterialID: "MAT-010", Qty: 4 * units},
		{MaterialID: "MAT-012", Qty: 0.2 * units},
	}
	for _, receipt := range receipts {
		var material domain.InventoryMaterials
		if err := db.First(&material, "material_id = ?", receipt.MaterialID).Error; err != nil {
			return err
		}
		material.CurrentStock += receipt.Qty
		material.Status = seedInventoryStatus(material.CurrentStock, material.MinStock)
		material.LastUpdated = time.Now().UTC()
		if err := db.Save(&material).Error; err != nil {
			return err
		}
		if err := db.Create(&domain.InventoryTransactions{
			TransactionID:   fmt.Sprintf("TXN-RPT-%s-%s", suffix, strings.ReplaceAll(receipt.MaterialID, "-", "")),
			MaterialID:      receipt.MaterialID,
			TransactionType: domain.TransactionTypeReceive,
			Quantity:        receipt.Qty,
			ReferenceJobID:  jobID,
			Timestamp:       ts,
			Notes:           "historical report seed receipt",
		}).Error; err != nil {
			return err
		}
	}
	return nil
}

type seedReportLogRequest struct {
	SlotID           string
	StartTime        time.Time
	EndTime          time.Time
	QuantityProduced int
	QuantityScrap    int
	OperatorNotes    string
}

func seedReportLogProduction(db *gorm.DB, req seedReportLogRequest) error {
	_, err := productionexec.LogProduction(db, productionexec.LogProductionRequest{
		SlotID:           req.SlotID,
		StartTime:        req.StartTime,
		EndTime:          req.EndTime,
		QuantityProduced: req.QuantityProduced,
		QuantityScrap:    req.QuantityScrap,
		OperatorNotes:    req.OperatorNotes,
	}, productionexec.Options{
		ProductionID:           "PL-RPT-" + strings.TrimPrefix(req.SlotID, "SLOT-RPT-"),
		ProductStorageLocation: "FG-RPT",
		TransactionID: func(slotID, _ string, materialID string) string {
			return fmt.Sprintf("TXN-RPT-CONSUME-%s-%s", strings.TrimPrefix(slotID, "SLOT-RPT-"), strings.ReplaceAll(materialID, "-", ""))
		},
		ProductInventoryID: func(slotID, productID string) string {
			return fmt.Sprintf("PINV-RPT-%s-%s", strings.TrimPrefix(slotID, "SLOT-RPT-"), strings.ReplaceAll(productID, "-", ""))
		},
		WIPID: func(slotID, productID string) string {
			return fmt.Sprintf("WIP-RPT-%s-%s", strings.TrimPrefix(slotID, "SLOT-RPT-"), strings.ReplaceAll(productID, "-", ""))
		},
		ConsumeNotes: func(_, _, _ string) string {
			return "historical report seed consumption"
		},
	})
	return err
}

func seedRefreshReportExecution(db *gorm.DB, slot *domain.JobStepScheduleSlots, step *domain.JobSteps) error {
	slot.Status = domain.SlotStatusCompleted
	slot.ActualStart = &slot.ScheduledStart
	slot.ActualEnd = &slot.ScheduledEnd
	if err := db.Save(slot).Error; err != nil {
		return err
	}

	var slots []domain.JobStepScheduleSlots
	if err := db.Where("job_step_id = ?", step.JobStepID).Find(&slots).Error; err != nil {
		return err
	}
	totalProduced := 0
	totalAccounted := 0
	totalPlanned := 0
	for _, st := range slots {
		totalPlanned += st.QuantityPlanned
		var logs []domain.ProductionLogs
		if err := db.Where("slot_id = ?", st.SlotID).Find(&logs).Error; err != nil {
			return err
		}
		for _, log := range logs {
			totalProduced += log.QuantityProduced
			totalAccounted += log.QuantityProduced + log.QuantityScrap
		}
	}
	step.QuantityCompleted = seedMinInt(totalProduced, step.QuantityTarget)
	if step.QuantityCompleted >= step.QuantityTarget {
		step.Status = domain.JobStepStatusCompleted
	} else if totalPlanned > 0 && totalAccounted >= totalPlanned {
		step.Status = domain.JobStepStatusBlocked
	} else if totalAccounted > 0 {
		step.Status = domain.JobStepStatusRunning
	}
	if err := db.Save(step).Error; err != nil {
		return err
	}

	var job domain.Job
	if err := db.First(&job, "job_id = ?", step.JobID).Error; err != nil {
		return err
	}
	var steps []domain.JobSteps
	if err := db.Where("job_id = ?", job.JobID).Order("step_sequence ASC").Find(&steps).Error; err != nil {
		return err
	}
	minCompleted := steps[0].QuantityCompleted
	allCompleted := true
	anyBlocked := false
	anyProgress := false
	for _, st := range steps {
		if st.QuantityCompleted < minCompleted {
			minCompleted = st.QuantityCompleted
		}
		if st.Status != domain.JobStepStatusCompleted {
			allCompleted = false
		}
		if st.Status == domain.JobStepStatusBlocked {
			anyBlocked = true
		}
		if st.QuantityCompleted > 0 || st.Status == domain.JobStepStatusRunning {
			anyProgress = true
		}
	}
	job.QuantityCompleted = seedMinInt(minCompleted, job.QuantityTotal)
	if allCompleted && job.QuantityCompleted >= job.QuantityTotal {
		job.Status = domain.JobStatusCompleted
	} else if anyBlocked {
		job.Status = domain.JobStatusBlocked
	} else if anyProgress {
		job.Status = domain.JobStatusRunning
	}
	job.UpdatedAt = time.Now().UTC()
	return db.Save(&job).Error
}

func seedMinInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func seedInventoryStatus(currentStock, minStock float64) string {
	if currentStock <= 0 {
		return domain.InventoryStatusOutOfStock
	}
	if currentStock < minStock {
		return domain.InventoryStatusLowStock
	}
	return domain.InventoryStatusInStock
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
	seedReportMaintenance(db)
	downtimes := []domain.MachineDowntime{
		{DowntimeID: id.NewPrefixed("DT-"), MachineID: "M-CNC-01", Cause: "Coolant pump low pressure alarm", StartTime: parseTime("2026-01-06T09:00:00Z"), EndTime: parseTime("2026-01-06T09:10:00Z"), DurationMinutes: 10},
		{DowntimeID: id.NewPrefixed("DT-"), MachineID: "M-CTG-01", Cause: "Coating solution temperature out of range", StartTime: parseTime("2026-01-07T10:30:00Z"), EndTime: parseTime("2026-01-07T10:45:00Z"), DurationMinutes: 15},
	}
	for _, d := range downtimes {
		_ = downtimeRepo.Create(&d)
	}
}

func seedReportMaintenance(db *gorm.DB) {
	mntRepo := repository.NewMaintenanceRepository(db)
	now := time.Now().UTC().Truncate(24 * time.Hour)
	_ = db.Exec("DELETE FROM maintenance_records WHERE maintenance_id LIKE 'MNT-RPT-%'").Error
	maints := []domain.MaintenanceRecords{
		{MaintenanceID: "MNT-RPT-001", MachineID: "M-PRS-01", MaintenanceType: "preventive", Technician: "Seed Technician", StartTime: now.AddDate(0, 0, -13).Add(6 * time.Hour), EndTime: now.AddDate(0, 0, -13).Add(8 * time.Hour), Description: "Historical report seed maintenance"},
		{MaintenanceID: "MNT-RPT-002", MachineID: "M-CTG-01", MaintenanceType: "corrective", Technician: "Seed Technician", StartTime: now.AddDate(0, 0, -5).Add(7 * time.Hour), EndTime: now.AddDate(0, 0, -5).Add(9 * time.Hour), Description: "Historical report seed maintenance"},
	}
	for _, m := range maints {
		_ = mntRepo.Create(&m)
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

func AssertCanonicalFingerprint(db *gorm.DB) error {
	if db == nil {
		return fmt.Errorf("seed fingerprint: db is nil")
	}
	checks := []struct {
		table string
		col   string
		ids   []string
	}{
		{table: "machines", col: "machine_id", ids: []string{"M-CNC-01"}},
		{table: "products", col: "product_id", ids: []string{"P-001", "P-002", "P-003", "P-004", "P-005", "P-006", "P-007", "P-008", "P-009"}},
		{table: "inventory_materials", col: "material_id", ids: []string{"MAT-001", "MAT-002", "MAT-003", "MAT-004", "MAT-005", "MAT-006", "MAT-007", "MAT-008", "MAT-009", "MAT-010", "MAT-011", "MAT-012", "MAT-013", "MAT-014"}},
		{table: "jobs", col: "job_id", ids: []string{"JOB-SEED-001", "JOB-SEED-002", "JOB-SEED-003", "JOB-SEED-004", "JOB-SEED-005", "JOB-SEED-006", "JOB-SEED-007", "JOB-SEED-008", "JOB-SEED-009", "JOB-SEED-010", "JOB-SEED-011", "JOB-SEED-012", "JOB-SEED-013", "JOB-SEED-014", "JOB-SEED-015", "JOB-SEED-016", "JOB-SEED-017", "JOB-SEED-018", "JOB-SEED-019", "JOB-SEED-020", "JOB-SEED-021", "JOB-SEED-022", "JOB-SEED-023", "JOB-SEED-024", "JOB-SEED-025", "JOB-SEED-026", "JOB-RPT-001", "JOB-RPT-002", "JOB-RPT-003", "JOB-RPT-004", "JOB-RPT-005"}},
		{table: "ai_proposals", col: "proposal_id", ids: []string{"AIPROP-SEED-001"}},
	}
	for _, check := range checks {
		var count int64
		if err := db.Table(check.table).Where(check.col+" IN ?", check.ids).Count(&count).Error; err != nil {
			return fmt.Errorf("seed fingerprint %s: %w", check.table, err)
		}
		if count != int64(len(check.ids)) {
			return fmt.Errorf("seed fingerprint %s.%s expected %d ids, found %d", check.table, check.col, len(check.ids), count)
		}
	}
	return nil
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
