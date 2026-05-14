package handler_test

import (
	"encoding/json"
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestJobHandler_CreateGetListUpdateDelete(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	// Create product first (job needs product_id)
	createProduct := map[string]interface{}{
		"product_id": "P-TEST", "product_name": "Test Product", "unit_of_measure": "pcs",
	}
	w := testutil.Request(r, "POST", "/api/v1/products", createProduct)
	if w.Code != http.StatusCreated {
		t.Fatalf("create product: got %d, want 201", w.Code)
	}

	// Create job
	createJob := map[string]interface{}{
		"product_id": "P-TEST", "quantity_total": 100, "priority": "high",
		"deadline": "2026-06-01T12:00:00Z", "notes": "test",
	}
	w = testutil.Request(r, "POST", "/api/v1/jobs", createJob)
	if w.Code != http.StatusCreated {
		t.Fatalf("create job: got %d, want 201, body: %s", w.Code, w.Body.String())
	}
	success, data, errMsg := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("create job failed: %s", errMsg)
	}
	m, ok := data.(map[string]interface{})
	if !ok {
		t.Fatalf("expected map, got %T", data)
	}
	jobID, _ := m["job_id"].(string)
	if jobID == "" {
		t.Fatal("job_id empty")
	}

	// Get by ID
	w = testutil.Request(r, "GET", "/api/v1/jobs/"+jobID, nil)
	if w.Code != http.StatusOK {
		t.Fatalf("get job: got %d", w.Code)
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatal("get job failed")
	}
	m = data.(map[string]interface{})
	if m["quantity_total"] != float64(100) {
		t.Errorf("quantity_total: got %v", m["quantity_total"])
	}

	// List
	w = testutil.Request(r, "GET", "/api/v1/jobs", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("list jobs: got %d", w.Code)
	}
	var listResp struct {
		Success bool          `json:"success"`
		Data    []interface{} `json:"data"`
	}
	json.Unmarshal(w.Body.Bytes(), &listResp)
	if !listResp.Success || len(listResp.Data) < 1 {
		t.Errorf("list jobs: success=%v, len=%d", listResp.Success, len(listResp.Data))
	}

	w = testutil.Request(r, "GET", "/api/v1/jobs?priority=high&fields=job_id,priority", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("list projected jobs: got %d", w.Code)
	}
	var projectedResp struct {
		Success bool                     `json:"success"`
		Data    []map[string]interface{} `json:"data"`
	}
	json.Unmarshal(w.Body.Bytes(), &projectedResp)
	if !projectedResp.Success || len(projectedResp.Data) < 1 {
		t.Fatalf("list projected jobs: success=%v, len=%d", projectedResp.Success, len(projectedResp.Data))
	}
	if _, ok := projectedResp.Data[0]["job_id"]; !ok {
		t.Fatalf("projected job missing job_id: %#v", projectedResp.Data[0])
	}
	if _, ok := projectedResp.Data[0]["priority"]; !ok {
		t.Fatalf("projected job missing priority: %#v", projectedResp.Data[0])
	}
	if _, ok := projectedResp.Data[0]["notes"]; ok {
		t.Fatalf("projected job should not include notes: %#v", projectedResp.Data[0])
	}

	// Update
	updateBody := map[string]interface{}{"status": "scheduled"}
	w = testutil.Request(r, "PUT", "/api/v1/jobs/"+jobID, updateBody)
	if w.Code != http.StatusOK {
		t.Fatalf("update job: got %d", w.Code)
	}

	// Duplicate
	dupBody := map[string]interface{}{"quantity": 50}
	w = testutil.Request(r, "POST", "/api/v1/jobs/"+jobID+"/duplicate", dupBody)
	if w.Code != http.StatusCreated {
		t.Fatalf("duplicate: got %d", w.Code)
	}

	// Delete
	w = testutil.Request(r, "DELETE", "/api/v1/jobs/"+jobID, nil)
	if w.Code != http.StatusOK {
		t.Fatalf("delete: got %d", w.Code)
	}

	// Get deleted should 404
	w = testutil.Request(r, "GET", "/api/v1/jobs/"+jobID, nil)
	if w.Code != http.StatusNotFound {
		t.Fatalf("get deleted: got %d, want 404", w.Code)
	}
}

func TestJobHandler_ListWithFilters(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/jobs?product_id=P1&status=planned&sort_by=deadline&sort_dir=asc", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("list filtered: got %d", w.Code)
	}
	success, _, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("list filtered failed")
	}

	w = testutil.Request(r, "GET", "/api/v1/jobs?status=unknown", nil)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("list invalid status: got %d, want 400", w.Code)
	}

	w = testutil.Request(r, "GET", "/api/v1/jobs?priority=critical", nil)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("list invalid priority: got %d, want 400", w.Code)
	}
}

func TestJobHandler_GetNotFound(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	w := testutil.Request(r, "GET", "/api/v1/jobs/nonexistent", nil)
	if w.Code != http.StatusNotFound {
		t.Fatalf("get nonexistent: got %d, want 404", w.Code)
	}
}

func TestJobHandler_CreateValidationError(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "", "quantity_total": 0,
	})
	if w.Code != http.StatusBadRequest {
		t.Fatalf("create invalid: got %d, want 400", w.Code)
	}

	w = testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-TEST-INVALID", "product_name": "Test Product", "unit_of_measure": "pcs",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create product for invalid status update: got %d, want 201", w.Code)
	}

	w = testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-TEST-INVALID", "quantity_total": 10,
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create job for invalid status update: got %d, want 201", w.Code)
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("job create failed")
	}
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "PUT", "/api/v1/jobs/"+jobID, map[string]interface{}{
		"status": "unknown",
	})
	if w.Code != http.StatusBadRequest {
		t.Fatalf("update invalid status: got %d, want 400", w.Code)
	}
}
