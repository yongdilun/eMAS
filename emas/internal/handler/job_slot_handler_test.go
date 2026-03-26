package handler_test

import (
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestJobSlotHandler_CreateJobStepsSplitUpdateCancel(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	// Create product, process, steps
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-SLOT", "product_name": "Slot Test", "unit_of_measure": "pcs",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-SLOT", "product_id": "P-SLOT", "process_name": "Slot Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-SLOT/steps", map[string]interface{}{
		"step_name": "Cut", "machine_type_required": "CNC",
	})
	// Create machine
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-SLOT", "machine_name": "CNC 1", "machine_type": "CNC",
	})
	// Create job
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-SLOT", "quantity_total": 50, "priority": "medium",
		"deadline": "2026-06-15T12:00:00Z",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create job: got %d", w.Code)
	}
	_, data, _ := testutil.DecodeResponse(w)
	m := data.(map[string]interface{})
	jobID := m["job_id"].(string)

	// Create job steps from routing
	w = testutil.Request(r, "POST", "/api/v1/job-steps", map[string]interface{}{"job_id": jobID})
	if w.Code != http.StatusCreated {
		t.Fatalf("create job steps: got %d, body: %s", w.Code, w.Body.String())
	}

	// List steps
	w = testutil.Request(r, "GET", "/api/v1/jobs/"+jobID+"/steps", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("list steps: got %d", w.Code)
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("list steps failed")
	}
	steps, _ := data.([]interface{})
	if len(steps) == 0 {
		t.Fatal("expected at least 1 step")
	}
	step0 := steps[0].(map[string]interface{})
	jobStepID := step0["job_step_id"].(string)

	// Split step
	splitBody := map[string]interface{}{
		"job_step_id": jobStepID,
		"splits": []map[string]interface{}{
			{"machine_id": "M-SLOT", "start_time": "2026-06-10T08:00:00Z", "duration_mins": 60, "quantity": 25},
		},
	}
	w = testutil.Request(r, "POST", "/api/v1/job-steps/split", splitBody)
	if w.Code != http.StatusCreated {
		t.Fatalf("split step: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatal("split failed")
	}
	slots, _ := data.([]interface{})
	if len(slots) < 1 {
		t.Fatal("expected slot")
	}
	slot0 := slots[0].(map[string]interface{})
	slotID := slot0["slot_id"].(string)

	// Get slot
	w = testutil.Request(r, "GET", "/api/v1/slots/"+slotID, nil)
	if w.Code != http.StatusOK {
		t.Fatalf("get slot: got %d", w.Code)
	}

	// List slots by job
	w = testutil.Request(r, "GET", "/api/v1/jobs/"+jobID+"/slots", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("list slots by job: got %d", w.Code)
	}

	// Cancel slot
	w = testutil.Request(r, "DELETE", "/api/v1/slots/"+slotID, nil)
	if w.Code != http.StatusOK {
		t.Fatalf("cancel slot: got %d", w.Code)
	}
}

func TestJobSlotHandler_CreateJobSteps_JobNotFound(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	w := testutil.Request(r, "POST", "/api/v1/job-steps", map[string]interface{}{"job_id": "nonexistent"})
	if w.Code != http.StatusInternalServerError {
		t.Fatalf("expected 500 for missing job, got %d", w.Code)
	}
}
