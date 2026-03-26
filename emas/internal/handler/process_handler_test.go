package handler_test

import (
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestProcessHandler_CRUD(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-PRC", "product_name": "Proc Product", "unit_of_measure": "pcs",
	})

	// Create
	w := testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-TEST", "product_id": "P-PRC", "process_name": "Assembly",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create: got %d", w.Code)
	}

	// Get
	w = testutil.Request(r, "GET", "/api/v1/processes/PRC-TEST", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("get: got %d", w.Code)
	}

	// Get by product
	w = testutil.Request(r, "GET", "/api/v1/products/P-PRC/process", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("get by product: got %d", w.Code)
	}

	// Add step
	w = testutil.Request(r, "POST", "/api/v1/processes/PRC-TEST/steps", map[string]interface{}{
		"step_name": "Cutting", "machine_type_required": "CNC",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("add step: got %d", w.Code)
	}

	// List steps
	w = testutil.Request(r, "GET", "/api/v1/processes/PRC-TEST/steps", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("list steps: got %d", w.Code)
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("list steps failed")
	}
	steps, _ := data.([]interface{})
	if len(steps) < 1 {
		t.Error("expected at least 1 step")
	}

	// Delete
	w = testutil.Request(r, "DELETE", "/api/v1/processes/PRC-TEST", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("delete: got %d", w.Code)
	}

	// Get deleted -> 404
	w = testutil.Request(r, "GET", "/api/v1/processes/PRC-TEST", nil)
	if w.Code != http.StatusNotFound {
		t.Fatalf("get deleted: got %d, want 404", w.Code)
	}
}
