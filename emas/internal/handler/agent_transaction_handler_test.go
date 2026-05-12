package handler_test

import (
	"bytes"
	"emas/internal/domain"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"

	"github.com/gin-gonic/gin"
)

func requestJSONWithHeaders(r *gin.Engine, method, path string, body interface{}, headers map[string]string) *httptest.ResponseRecorder {
	var reader *bytes.Reader
	if body == nil {
		reader = bytes.NewReader(nil)
	} else {
		raw, _ := json.Marshal(body)
		reader = bytes.NewReader(raw)
	}
	req := httptest.NewRequest(method, path, reader)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func stagedMachine(machineID string) map[string]interface{} {
	return map[string]interface{}{
		"intent_id":        "i1",
		"decision_id":      "d1",
		"tool_call_id":     "tc1",
		"tool_name":        "post__machines",
		"output_ref":       "$ref:machine",
		"idempotency_key":  "idem-" + machineID,
		"write_generation": 1,
		"args": map[string]interface{}{
			"machine_id":        machineID,
			"machine_name":      "Transaction Machine",
			"machine_type":      "CNC",
			"capacity_per_hour": 20,
		},
	}
}

func stagedWrite(toolName, key, outputRef string, args map[string]interface{}) map[string]interface{} {
	return map[string]interface{}{
		"intent_id":        "i1",
		"decision_id":      "d1",
		"tool_call_id":     key,
		"tool_name":        toolName,
		"output_ref":       outputRef,
		"idempotency_key":  "idem-" + key,
		"write_generation": 1,
		"args":             args,
	}
}

func TestAgentTransactionBundleDryRunDoesNotCommit(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "POST", "/api/v1/agent/transaction/bundle-dry-run", map[string]interface{}{
		"staged_writes": []interface{}{stagedMachine("M-DRY-RUN")},
	})
	if w.Code != http.StatusOK {
		t.Fatalf("dry-run: got %d, body: %s", w.Code, w.Body.String())
	}

	w = testutil.Request(r, "GET", "/api/v1/machines/M-DRY-RUN", nil)
	if w.Code != http.StatusNotFound {
		t.Fatalf("dry-run committed a machine: got %d, want 404", w.Code)
	}
}

func TestAgentTransactionCommitIsAtomicAndIdempotent(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	body := map[string]interface{}{
		"bundle_idempotency_key": "bundle-machine-commit",
		"staged_writes":          []interface{}{stagedMachine("M-COMMIT")},
	}
	headers := map[string]string{"Idempotency-Key": "bundle-machine-commit"}

	w := requestJSONWithHeaders(r, "POST", "/api/v1/agent/transaction/commit", body, headers)
	if w.Code != http.StatusOK {
		t.Fatalf("commit: got %d, body: %s", w.Code, w.Body.String())
	}

	w = requestJSONWithHeaders(r, "POST", "/api/v1/agent/transaction/commit", body, headers)
	if w.Code != http.StatusOK {
		t.Fatalf("idempotent replay: got %d, body: %s", w.Code, w.Body.String())
	}
	if w.Header().Get("X-Idempotent-Replayed") != "true" {
		t.Fatalf("expected idempotent replay header, got %q", w.Header().Get("X-Idempotent-Replayed"))
	}

	w = testutil.Request(r, "GET", "/api/v1/machines/M-COMMIT", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("committed machine missing: got %d, body: %s", w.Code, w.Body.String())
	}
}

func TestAgentTransactionCommitRollsBackWholeBundleOnBusinessConflict(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-CONFLICT", "machine_name": "Existing", "machine_type": "CNC",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("seed machine: got %d, body: %s", w.Code, w.Body.String())
	}

	body := map[string]interface{}{
		"bundle_idempotency_key": "bundle-conflict",
		"staged_writes": []interface{}{
			stagedMachine("M-ROLLBACK"),
			stagedMachine("M-CONFLICT"),
		},
	}
	w = requestJSONWithHeaders(
		r,
		"POST",
		"/api/v1/agent/transaction/commit",
		body,
		map[string]string{"Idempotency-Key": "bundle-conflict"},
	)
	if w.Code != http.StatusConflict {
		t.Fatalf("conflict commit: got %d, want 409, body: %s", w.Code, w.Body.String())
	}

	w = testutil.Request(r, "GET", "/api/v1/machines/M-ROLLBACK", nil)
	if w.Code != http.StatusNotFound {
		t.Fatalf("bundle was not rolled back: got %d, want 404", w.Code)
	}
}

func TestAgentTransactionCommitSupportsProductInventoryAndRefs(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	body := map[string]interface{}{
		"bundle_idempotency_key": "bundle-product-inventory",
		"staged_writes": []interface{}{
			stagedWrite("post__products", "product", "$ref:product", map[string]interface{}{
				"product_id":      "P-BUNDLE",
				"product_name":    "Bundled Product",
				"unit_of_measure": "pcs",
			}),
			stagedWrite("post__inventory_materials", "material", "$ref:material", map[string]interface{}{
				"material_id":   "MAT-BUNDLE",
				"material_name": "Bundled Resin",
				"unit":          "kg",
				"current_stock": 10,
				"min_stock":     5,
				"reorder_level": 8,
			}),
			stagedWrite("post__inventory_receive", "receive", "", map[string]interface{}{
				"material_id": "$ref:material",
				"quantity":    7,
			}),
			stagedWrite("post__inventory_product-stock", "product-stock", "", map[string]interface{}{
				"product_id":       "$ref:product",
				"quantity_on_hand": 3,
			}),
			stagedWrite("post__inventory_reservations", "reservation", "", map[string]interface{}{
				"material_id":    "$ref:material",
				"reserved_qty":   2,
				"needed_at":      "2026-06-01T00:00:00Z",
				"reference_note": "agent bundle",
			}),
		},
	}

	w := requestJSONWithHeaders(
		r,
		"POST",
		"/api/v1/agent/transaction/commit",
		body,
		map[string]string{"Idempotency-Key": "bundle-product-inventory"},
	)
	if w.Code != http.StatusOK {
		t.Fatalf("commit product/inventory bundle: got %d, body: %s", w.Code, w.Body.String())
	}

	w = testutil.Request(r, "GET", "/api/v1/products/P-BUNDLE", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("product missing after bundle: got %d, body: %s", w.Code, w.Body.String())
	}
	w = testutil.Request(r, "GET", "/api/v1/inventory/materials/MAT-BUNDLE", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("material missing after bundle: got %d, body: %s", w.Code, w.Body.String())
	}
	var material domain.InventoryMaterials
	if err := db.Where("material_id = ?", "MAT-BUNDLE").First(&material).Error; err != nil {
		t.Fatalf("load material: %v", err)
	}
	if material.CurrentStock != 17 {
		t.Fatalf("material stock got %v, want 17", material.CurrentStock)
	}
	var productInventoryCount int64
	if err := db.Model(&domain.ProductInventory{}).Where("product_id = ?", "P-BUNDLE").Count(&productInventoryCount).Error; err != nil {
		t.Fatalf("count product inventory: %v", err)
	}
	if productInventoryCount != 1 {
		t.Fatalf("product inventory count got %d, want 1", productInventoryCount)
	}
}

func TestAgentTransactionCommitSupportsMachineOperationalWritesWithRefs(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	body := map[string]interface{}{
		"bundle_idempotency_key": "bundle-machine-ops",
		"staged_writes": []interface{}{
			stagedMachine("M-OPS"),
			stagedWrite("post__machines_{id}_capabilities", "capability", "", map[string]interface{}{
				"id":                "$ref:machine",
				"step_id":           "STP-BUNDLE",
				"efficiency_factor": 1.2,
			}),
			stagedWrite("post__machines_downtime", "downtime", "", map[string]interface{}{
				"machine_id": "$ref:machine",
				"cause":      "planned test",
				"start_time": "2026-06-01T01:00:00Z",
				"end_time":   "2026-06-01T02:00:00Z",
			}),
			stagedWrite("post__maintenance", "maintenance", "", map[string]interface{}{
				"machine_id":       "$ref:machine",
				"maintenance_type": "preventive",
				"technician":       "Agent",
				"description":      "bundle check",
				"start_time":       "2026-06-02T01:00:00Z",
				"end_time":         "2026-06-02T02:00:00Z",
			}),
		},
	}

	w := requestJSONWithHeaders(
		r,
		"POST",
		"/api/v1/agent/transaction/commit",
		body,
		map[string]string{"Idempotency-Key": "bundle-machine-ops"},
	)
	if w.Code != http.StatusOK {
		t.Fatalf("commit machine ops bundle: got %d, body: %s", w.Code, w.Body.String())
	}

	var capabilities, downtime, maintenance int64
	if err := db.Model(&domain.MachineCapabilities{}).Where("machine_id = ?", "M-OPS").Count(&capabilities).Error; err != nil {
		t.Fatalf("count capabilities: %v", err)
	}
	if err := db.Model(&domain.MachineDowntime{}).Where("machine_id = ?", "M-OPS").Count(&downtime).Error; err != nil {
		t.Fatalf("count downtime: %v", err)
	}
	if err := db.Model(&domain.MaintenanceRecords{}).Where("machine_id = ?", "M-OPS").Count(&maintenance).Error; err != nil {
		t.Fatalf("count maintenance: %v", err)
	}
	if capabilities != 1 || downtime != 1 || maintenance != 1 {
		t.Fatalf("counts got capabilities=%d downtime=%d maintenance=%d, want all 1", capabilities, downtime, maintenance)
	}
}
