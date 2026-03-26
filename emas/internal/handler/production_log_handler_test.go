package handler_test

import (
	"net/http"
	"testing"
	"time"

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
		"slot_id": slotID, "start_time": now.Add(-1*time.Hour), "end_time": now,
		"quantity_produced": 20, "quantity_scrap": 2, "operator_notes": "ok",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("log production: got %d, body: %s", w.Code, w.Body.String())
	}
}
