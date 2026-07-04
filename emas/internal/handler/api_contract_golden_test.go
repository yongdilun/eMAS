package handler_test

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"

	"emas/internal/domain"
	"emas/internal/router"
	"emas/internal/testutil"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

func TestAPIContractGoldenJobs(t *testing.T) {
	db := testutil.NewTestDB(t)
	seedGoldenJobContract(t, db)
	r := testutil.NewTestRouter(db, router.Setup)

	assertGoldenResponse(t, r, http.MethodGet, "/api/v1/jobs/JOB-GOLDEN", nil, http.StatusOK, "jobs_get_with_deadline_status.json")
}

func TestAPIContractGoldenMachines(t *testing.T) {
	db := testutil.NewTestDB(t)
	seedGoldenMachineContract(t, db)
	r := testutil.NewTestRouter(db, router.Setup)

	assertGoldenResponse(t, r, http.MethodGet, "/api/v1/machines?sort_by=machine_id&sort_dir=asc&limit=1", nil, http.StatusOK, "machines_list_legacy_domain_casing.json")
}

func TestAPIContractGoldenProductsAndFormulas(t *testing.T) {
	db := testutil.NewTestDB(t)
	seedGoldenProductFormulaContract(t, db)
	r := testutil.NewTestRouter(db, router.Setup)

	assertGoldenResponse(t, r, http.MethodGet, "/api/v1/products/P-GOLDEN", nil, http.StatusOK, "products_get_legacy_domain_casing.json")
	assertGoldenResponse(t, r, http.MethodGet, "/api/v1/formulas/F-GOLDEN", nil, http.StatusOK, "formulas_get_legacy_domain_casing.json")
}

func TestAPIContractGoldenInventory(t *testing.T) {
	db := testutil.NewTestDB(t)
	seedGoldenInventoryContract(t, db)
	r := testutil.NewTestRouter(db, router.Setup)

	assertGoldenResponse(t, r, http.MethodGet, "/api/v1/inventory/materials?sort_by=material_name&sort_dir=asc&limit=1", nil, http.StatusOK, "inventory_materials_list_legacy_domain_casing.json")
	assertGoldenResponse(t, r, http.MethodGet, "/api/v1/inventory/product-stock?product_id=P-GOLDEN&sort_by=product_id&sort_dir=asc&limit=1", nil, http.StatusOK, "inventory_product_stock_list_legacy_domain_casing.json")
	assertGoldenResponse(t, r, http.MethodGet, "/api/v1/inventory/reservations?material_id=MAT-GOLDEN", nil, http.StatusOK, "inventory_reservations_list_legacy_domain_casing.json")
}

func seedGoldenJobContract(t *testing.T, db *gorm.DB) {
	t.Helper()
	base := time.Date(2026, 5, 20, 10, 0, 0, 0, time.UTC)
	mustCreate(t, db, &domain.Product{
		ProductID:     "P-GOLDEN",
		ProductName:   "Golden Product",
		UnitOfMeasure: "pcs",
		ProductType:   "assembly",
		Status:        domain.ProductStatusActive,
		CreatedAt:     base.Add(-48 * time.Hour),
	})
	mustCreate(t, db, &domain.Job{
		JobID:             "JOB-GOLDEN",
		ProductID:         "P-GOLDEN",
		QuantityTotal:     100,
		QuantityCompleted: 25,
		Priority:          domain.JobPriorityHigh,
		Deadline:          base.Add(2 * time.Hour),
		Status:            domain.JobStatusScheduled,
		CreatedAt:         base.Add(-24 * time.Hour),
		UpdatedAt:         base.Add(-12 * time.Hour),
		Notes:             "contract sample",
	})
	mustCreate(t, db, &domain.JobSteps{
		JobStepID:         "JS-GOLDEN",
		JobID:             "JOB-GOLDEN",
		StepID:            "STEP-GOLDEN",
		StepSequence:      1,
		QuantityTarget:    100,
		QuantityCompleted: 25,
		Status:            domain.JobStepStatusScheduled,
	})
	mustCreate(t, db, &domain.JobStepScheduleSlots{
		SlotID:            "SLOT-GOLDEN",
		JobStepID:         "JS-GOLDEN",
		MachineID:         "M-GOLDEN",
		ScheduledStart:    base,
		ScheduledEnd:      base.Add(4 * time.Hour),
		QuantityPlanned:   100,
		SplitGroupID:      "SG-GOLDEN",
		AllocationPercent: 100,
		Status:            domain.SlotStatusPlanned,
	})
}

func seedGoldenMachineContract(t *testing.T, db *gorm.DB) {
	t.Helper()
	lastMaintenance := time.Date(2026, 5, 1, 8, 30, 0, 0, time.UTC)
	mustCreate(t, db, &domain.Machine{
		MachineID:               "M-GOLDEN",
		MachineName:             "Golden CNC",
		MachineType:             "CNC",
		Location:                "Cell A",
		Status:                  domain.MachineStatusRunning,
		CapacityPerHour:         42,
		DefaultSetupTime:        15,
		DefaultCleaningTime:     10,
		DefaultChangeoverTime:   20,
		UtilizationRate:         87.5,
		LastMaintenanceDate:     &lastMaintenance,
		MaintenanceIntervalDays: 30,
	})
}

func seedGoldenProductFormulaContract(t *testing.T, db *gorm.DB) {
	t.Helper()
	base := time.Date(2026, 5, 20, 10, 0, 0, 0, time.UTC)
	mustCreate(t, db, &domain.Formula{
		FormulaID:    "F-GOLDEN",
		FormulaName:  "Golden Formula",
		Version:      3,
		Instructions: "Mix carefully",
		SafetyNotes:  "Wear gloves",
		CreatedAt:    base.Add(-72 * time.Hour),
	})
	mustCreate(t, db, &domain.Product{
		ProductID:     "P-GOLDEN",
		ProductName:   "Golden Product",
		Description:   "Contract fixture product",
		UnitOfMeasure: "pcs",
		ProductType:   "assembly",
		Status:        domain.ProductStatusActive,
		FormulaID:     "F-GOLDEN",
		ProcessID:     "PRC-GOLDEN",
		CreatedAt:     base.Add(-48 * time.Hour),
	})
}

func seedGoldenInventoryContract(t *testing.T, db *gorm.DB) {
	t.Helper()
	base := time.Date(2026, 5, 20, 10, 0, 0, 0, time.UTC)
	mustCreate(t, db, &domain.InventoryMaterials{
		MaterialID:      "MAT-GOLDEN",
		MaterialName:    "Golden Alloy",
		Unit:            "kg",
		CurrentStock:    123.5,
		MinStock:        25,
		ReorderLevel:    50,
		StorageLocation: "Rack G",
		Status:          domain.InventoryStatusInStock,
		LastUpdated:     base,
	})
	mustCreate(t, db, &domain.ProductInventory{
		InventoryID:      "PINV-GOLDEN",
		ProductID:        "P-GOLDEN",
		QuantityOnHand:   80,
		QuantityReserved: 15,
		Status:           domain.ProductInventoryStatusAvailable,
		StorageLocation:  "Finished G",
		AvailableFrom:    base.Add(24 * time.Hour),
		LastUpdated:      base,
	})
	mustCreate(t, db, &domain.Job{
		JobID:         "JOB-GOLDEN",
		ProductID:     "P-GOLDEN",
		QuantityTotal: 100,
		Priority:      domain.JobPriorityMedium,
		Deadline:      base.Add(48 * time.Hour),
		Status:        domain.JobStatusScheduled,
		CreatedAt:     base.Add(-24 * time.Hour),
		UpdatedAt:     base.Add(-12 * time.Hour),
	})
	mustCreate(t, db, &domain.JobSteps{
		JobStepID:      "JS-GOLDEN",
		JobID:          "JOB-GOLDEN",
		StepID:         "STEP-GOLDEN",
		StepSequence:   1,
		QuantityTarget: 100,
		Status:         domain.JobStepStatusScheduled,
	})
	mustCreate(t, db, &domain.InventoryReservation{
		ReservationID: "RES-GOLDEN",
		MaterialID:    "MAT-GOLDEN",
		JobID:         "JOB-GOLDEN",
		JobStepID:     "JS-GOLDEN",
		ReservedQty:   12.5,
		NeededAt:      base.Add(2 * time.Hour),
		Status:        domain.InventoryReservationStatusPending,
		CreatedAt:     base.Add(-2 * time.Hour),
		UpdatedAt:     base.Add(-1 * time.Hour),
	})
}

func mustCreate(t *testing.T, db *gorm.DB, value interface{}) {
	t.Helper()
	if err := db.Create(value).Error; err != nil {
		t.Fatalf("seed %T: %v", value, err)
	}
}

func assertGoldenResponse(t *testing.T, r *gin.Engine, method, path string, body interface{}, wantStatus int, fixture string) {
	t.Helper()
	w := testutil.Request(r, method, path, body)
	if w.Code != wantStatus {
		t.Fatalf("%s %s: got status %d, want %d, body: %s", method, path, w.Code, wantStatus, w.Body.String())
	}
	got := prettyJSON(t, w.Body.Bytes())
	fixturePath := filepath.Join("testdata", "golden", fixture)
	if os.Getenv("EMAS_UPDATE_GOLDEN") == "1" {
		if err := os.WriteFile(fixturePath, []byte(got+"\n"), 0o644); err != nil {
			t.Fatalf("update golden %s: %v", fixturePath, err)
		}
	}
	wantBytes, err := os.ReadFile(fixturePath)
	if err != nil {
		t.Fatalf("read golden %s: %v", fixturePath, err)
	}
	want := prettyJSON(t, wantBytes)
	if got != want {
		t.Fatalf("response did not match %s\n--- got ---\n%s\n--- want ---\n%s", fixture, got, want)
	}
}

func prettyJSON(t *testing.T, raw []byte) string {
	t.Helper()
	var payload interface{}
	if err := json.Unmarshal(raw, &payload); err != nil {
		t.Fatalf("unmarshal response: %v\nbody: %s", err, string(raw))
	}
	out, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		t.Fatalf("marshal normalized response: %v", err)
	}
	return string(out)
}
