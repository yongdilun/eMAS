package handler_test

import (
	"net/http"
	"testing"
	"time"

	"emas/internal/domain"
	"emas/internal/router"
	"emas/internal/testutil"
)

func TestProductionLogHandler_LogProduction(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	// Create product, process, machine, job, step, slot
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-PL", "product_name": "PL Product", "unit_of_measure": "pcs",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-PL", "product_id": "P-PL", "process_name": "PL Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-PL/steps", map[string]interface{}{
		"step_name": "Assemble", "machine_type_required": "CNC",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-PL", "machine_name": "CNC", "machine_type": "CNC",
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-PL", "quantity_total": 50, "deadline": "2026-07-01T12:00:00Z",
	})
	_, data, _ := testutil.DecodeResponse(w)
	m := data.(map[string]interface{})
	jobID := m["job_id"].(string)
	testutil.Request(r, "POST", "/api/v1/job-steps", map[string]interface{}{"job_id": jobID})
	w = testutil.Request(r, "GET", "/api/v1/jobs/"+jobID+"/steps", nil)
	_, data, _ = testutil.DecodeResponse(w)
	steps := data.([]interface{})
	jobStepID := steps[0].(map[string]interface{})["job_step_id"].(string)
	splitBody := map[string]interface{}{
		"job_step_id": jobStepID,
		"splits": []map[string]interface{}{
			{"machine_id": "M-PL", "start_time": "2026-06-15T08:00:00Z", "duration_mins": 60, "quantity": 25},
		},
	}
	testutil.Request(r, "POST", "/api/v1/job-steps/split", splitBody)
	w = testutil.Request(r, "GET", "/api/v1/jobs/"+jobID+"/slots", nil)
	_, data, _ = testutil.DecodeResponse(w)
	slots := data.([]interface{})
	if len(slots) == 0 {
		t.Skip("no slots")
	}
	slotID := slots[0].(map[string]interface{})["slot_id"].(string)

	now := time.Now()
	w = testutil.Request(r, "POST", "/api/v1/production-logs", map[string]interface{}{
		"slot_id": slotID, "start_time": now.Add(-1 * time.Hour), "end_time": now,
		"quantity_produced": 20, "quantity_scrap": 2, "operator_notes": "ok",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("log production: got %d, body: %s", w.Code, w.Body.String())
	}
}

func TestProductionLogHandler_MissingSlotReturnsNotFound(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	now := time.Now()
	w := testutil.Request(r, "POST", "/api/v1/production-logs", map[string]interface{}{
		"slot_id": "SLOT-MISSING", "start_time": now.Add(-1 * time.Hour), "end_time": now,
		"quantity_produced": 1,
	})
	if w.Code != http.StatusNotFound {
		t.Fatalf("missing slot: got %d, want 404, body: %s", w.Code, w.Body.String())
	}
	success, _, errMsg := testutil.DecodeResponse(w)
	if success || errMsg == "" {
		t.Fatalf("error envelope = success:%v error:%q, want failure with message", success, errMsg)
	}
}

func TestProductionLogHandler_LogProductionConsumesMaterialCreatesProductAndTracksProgress(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	mustCreated := func(method, path string, body interface{}) {
		t.Helper()
		w := testutil.Request(r, method, path, body)
		if w.Code != http.StatusCreated {
			t.Fatalf("%s %s: got %d body=%s", method, path, w.Code, w.Body.String())
		}
	}

	mustCreated("POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-EXEC-1", "product_name": "Execution Product", "unit_of_measure": "pcs",
	})
	mustCreated("POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-EXEC-1", "product_id": "P-EXEC-1", "process_name": "Execution Process",
	})
	mustCreated("POST", "/api/v1/processes/PRC-EXEC-1/steps", map[string]interface{}{
		"step_id": "STEP-EXEC-1", "step_sequence": 1, "step_name": "Build", "machine_type_required": "Assembly Station",
	})
	mustCreated("POST", "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-EXEC-1", "material_name": "Execution Material", "unit": "kg", "current_stock": 100, "min_stock": 5,
	})
	mustCreated("POST", "/api/v1/process-steps/STEP-EXEC-1/materials", map[string]interface{}{
		"material_id": "MAT-EXEC-1", "role": "input", "quantity_per_unit": 2, "unit": "kg",
	})
	mustCreated("POST", "/api/v1/process-steps/STEP-EXEC-1/materials", map[string]interface{}{
		"product_id": "P-EXEC-1", "role": "output", "quantity_per_unit": 1, "unit": "pcs",
	})
	mustCreated("POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-EXEC-1", "machine_name": "Execution Assembly", "machine_type": "Assembly Station",
	})

	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-EXEC-1", "quantity_total": 10, "deadline": "2026-07-20T12:00:00Z",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create job: got %d body=%s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	mustCreated("POST", "/api/v1/job-steps", map[string]interface{}{"job_id": jobID})
	w = testutil.Request(r, "GET", "/api/v1/jobs/"+jobID+"/steps", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("list steps: got %d body=%s", w.Code, w.Body.String())
	}
	_, data, _ = testutil.DecodeResponse(w)
	jobStepID := data.([]interface{})[0].(map[string]interface{})["job_step_id"].(string)

	mustCreated("POST", "/api/v1/job-steps/split", map[string]interface{}{
		"job_step_id": jobStepID,
		"splits": []map[string]interface{}{
			{"machine_id": "M-EXEC-1", "start_time": "2026-07-10T08:00:00Z", "duration_mins": 60, "quantity": 10},
		},
	})
	w = testutil.Request(r, "GET", "/api/v1/jobs/"+jobID+"/slots", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("list slots: got %d body=%s", w.Code, w.Body.String())
	}
	_, data, _ = testutil.DecodeResponse(w)
	slotID := data.([]interface{})[0].(map[string]interface{})["slot_id"].(string)

	start := time.Date(2026, 7, 10, 8, 0, 0, 0, time.UTC)
	end := start.Add(time.Hour)
	w = testutil.Request(r, "POST", "/api/v1/production-logs", map[string]interface{}{
		"slot_id": slotID, "start_time": start.Format(time.RFC3339), "end_time": end.Format(time.RFC3339),
		"quantity_produced": 10, "operator_notes": "execution test",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("log production: got %d body=%s", w.Code, w.Body.String())
	}

	var material domain.InventoryMaterials
	if err := db.First(&material, "material_id = ?", "MAT-EXEC-1").Error; err != nil {
		t.Fatalf("load material: %v", err)
	}
	if material.CurrentStock != 80 {
		t.Fatalf("material stock = %.2f, want 80.00", material.CurrentStock)
	}

	var tx domain.InventoryTransactions
	if err := db.First(&tx, "material_id = ? AND transaction_type = ?", "MAT-EXEC-1", domain.TransactionTypeConsume).Error; err != nil {
		t.Fatalf("load consume transaction: %v", err)
	}
	if tx.Quantity != 20 || tx.ReferenceJobID != jobID {
		t.Fatalf("consume tx quantity/reference = %.2f/%s, want 20/%s", tx.Quantity, tx.ReferenceJobID, jobID)
	}

	var productInventory domain.ProductInventory
	if err := db.First(&productInventory, "product_id = ? AND status = ?", "P-EXEC-1", domain.ProductInventoryStatusAvailable).Error; err != nil {
		t.Fatalf("load product inventory: %v", err)
	}
	if productInventory.QuantityOnHand != 10 {
		t.Fatalf("finished product quantity = %.2f, want 10", productInventory.QuantityOnHand)
	}

	var job domain.Job
	if err := db.First(&job, "job_id = ?", jobID).Error; err != nil {
		t.Fatalf("load job: %v", err)
	}
	if job.QuantityCompleted != 10 || job.Status != domain.JobStatusCompleted {
		t.Fatalf("job progress/status = %d/%s, want 10/completed", job.QuantityCompleted, job.Status)
	}

	var slot domain.JobStepScheduleSlots
	if err := db.First(&slot, "slot_id = ?", slotID).Error; err != nil {
		t.Fatalf("load slot: %v", err)
	}
	if slot.Status != domain.SlotStatusCompleted || slot.ActualStart == nil || slot.ActualEnd == nil {
		t.Fatalf("slot execution = status:%s actual_start:%v actual_end:%v, want completed with actual times", slot.Status, slot.ActualStart, slot.ActualEnd)
	}
	if !slot.ActualStart.Equal(start) || !slot.ActualEnd.Equal(end) {
		t.Fatalf("slot actual range = %v..%v, want %v..%v", slot.ActualStart, slot.ActualEnd, start, end)
	}
}
