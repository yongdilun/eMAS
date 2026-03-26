package handler_test

import (
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestProductHandler_CRUD(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	// Create
	w := testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-TEST", "product_name": "Widget", "unit_of_measure": "pcs",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create: got %d", w.Code)
	}

	// Get
	w = testutil.Request(r, "GET", "/api/v1/products/P-TEST", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("get: got %d", w.Code)
	}

	// List
	w = testutil.Request(r, "GET", "/api/v1/products", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("list: got %d", w.Code)
	}
}

func TestProductHandler_LinkBOM(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-BOM", "product_name": "Assembled", "unit_of_measure": "pcs",
	})
	// Create material first
	testutil.Request(r, "POST", "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-BOM", "material_name": "Raw", "current_stock": 100, "min_stock": 10,
	})

	w := testutil.Request(r, "PUT", "/api/v1/products/P-BOM/bom", map[string]interface{}{
		"bom_items": []map[string]interface{}{
			{"material_id": "MAT-BOM", "quantity_required": 2.5, "unit": "kg"},
		},
	})
	if w.Code != http.StatusOK {
		t.Fatalf("link BOM: got %d, body: %s", w.Code, w.Body.String())
	}
}
