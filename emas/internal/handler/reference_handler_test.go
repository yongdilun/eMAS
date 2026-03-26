package handler_test

import (
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestReferenceHandler_MachineTypes(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/reference/machine-types", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("GET machine-types: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("GET machine-types: success false")
	}
	arr, ok := data.([]interface{})
	if !ok {
		t.Fatalf("GET machine-types: data not array, got %T", data)
	}
	// After migration, table is empty until seeded
	_ = arr

	// Create
	w = testutil.Request(r, "POST", "/api/v1/reference/machine-types", map[string]interface{}{
		"name":        "Test CNC",
		"description": "Test machine type",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("POST machine-types: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatal("POST machine-types: success false")
	}
	m, ok := data.(map[string]interface{})
	if !ok {
		t.Fatalf("POST machine-types: data not map, got %T", data)
	}
	if _, ok := m["id"]; !ok {
		t.Error("POST machine-types: missing id")
	}
	if name, ok := m["name"].(string); !ok || name != "Test CNC" {
		t.Errorf("POST machine-types: name=%v", m["name"])
	}
}

func TestReferenceHandler_ProductTypes(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/reference/product-types", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("GET product-types: got %d", w.Code)
	}

	w = testutil.Request(r, "POST", "/api/v1/reference/product-types", map[string]interface{}{"name": "Test Product Type"})
	if w.Code != http.StatusCreated {
		t.Fatalf("POST product-types: got %d", w.Code)
	}
}

func TestReferenceHandler_Locations(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/reference/locations", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("GET locations: got %d", w.Code)
	}

	w = testutil.Request(r, "POST", "/api/v1/reference/locations", map[string]interface{}{
		"zone": "Floor X",
		"bay":  "Bay 1",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("POST locations: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("POST locations: success false")
	}
	m, ok := data.(map[string]interface{})
	if !ok {
		t.Fatalf("POST locations: data not map, got %T", data)
	}
	if disp, ok := m["display"].(string); !ok || disp != "Floor X – Bay 1" {
		t.Errorf("POST locations: display=%v", m["display"])
	}
}

func TestReferenceHandler_StorageLocations(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/reference/storage-locations", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("GET storage-locations: got %d", w.Code)
	}

	w = testutil.Request(r, "POST", "/api/v1/reference/storage-locations", map[string]interface{}{
		"name": "Test Shelf A",
		"type": "shelf",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("POST storage-locations: got %d", w.Code)
	}
}

func TestReferenceHandler_StepTypes(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/reference/step-types", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("GET step-types: got %d", w.Code)
	}

	w = testutil.Request(r, "POST", "/api/v1/reference/step-types", map[string]interface{}{
		"name":                 "Test Step",
		"default_machine_type": "CNC Mill",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("POST step-types: got %d", w.Code)
	}
}
