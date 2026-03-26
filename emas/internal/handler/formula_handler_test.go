package handler_test

import (
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestFormulaHandler_CRUD(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	// Create
	w := testutil.Request(r, "POST", "/api/v1/formulas", map[string]interface{}{
		"formula_id": "F-TEST", "formula_name": "Mix A", "version": 1,
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create: got %d", w.Code)
	}

	// Get
	w = testutil.Request(r, "GET", "/api/v1/formulas/F-TEST", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("get: got %d", w.Code)
	}

	// List
	w = testutil.Request(r, "GET", "/api/v1/formulas", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("list: got %d", w.Code)
	}
}

func TestFormulaHandler_Ingredients(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	testutil.Request(r, "POST", "/api/v1/formulas", map[string]interface{}{
		"formula_id": "F-ING", "formula_name": "Mix B",
	})
	testutil.Request(r, "POST", "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-F", "material_name": "Ing", "current_stock": 50, "min_stock": 5,
	})

	w := testutil.Request(r, "POST", "/api/v1/formulas/F-ING/ingredients", map[string]interface{}{
		"material_id": "MAT-F", "quantity": 1.5, "unit": "kg",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("add ingredient: got %d", w.Code)
	}

	w = testutil.Request(r, "GET", "/api/v1/formulas/F-ING/ingredients", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("list ingredients: got %d", w.Code)
	}
}
