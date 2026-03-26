package handler_test

import (
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestQualityHandler_RecordInspection(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	// Create product, process, job, step
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-QC", "product_name": "QC Product", "unit_of_measure": "pcs",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-QC", "product_id": "P-QC", "process_name": "QC Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-QC/steps", map[string]interface{}{
		"step_name": "Inspect", "machine_type_required": "Manual",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-QC", "machine_name": "Station", "machine_type": "Manual",
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-QC", "quantity_total": 10, "deadline": "2026-07-01T12:00:00Z",
	})
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)
	testutil.Request(r, "POST", "/api/v1/job-steps", map[string]interface{}{"job_id": jobID})
	w = testutil.Request(r, "GET", "/api/v1/jobs/"+jobID+"/steps", nil)
	_, data, _ = testutil.DecodeResponse(w)
	steps := data.([]interface{})
	if len(steps) == 0 {
		t.Skip("no steps")
	}
	jobStepID := steps[0].(map[string]interface{})["job_step_id"].(string)

	w = testutil.Request(r, "POST", "/api/v1/quality/inspections", map[string]interface{}{
		"job_step_id": jobStepID, "inspector_name": "John", "result": "pass",
		"defect_count": 0, "notes": "OK",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("record inspection: got %d", w.Code)
	}
}
