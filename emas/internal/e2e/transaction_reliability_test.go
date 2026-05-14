package e2e_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"emas/internal/domain"
	"emas/internal/router"
	"emas/internal/testutil"

	"github.com/gin-gonic/gin"
)

func reliabilityRequestJSONWithHeaders(r *gin.Engine, method, path string, body interface{}, headers map[string]string) *httptest.ResponseRecorder {
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
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func reliabilityStagedWrite(toolName, key, outputRef string, args map[string]interface{}) map[string]interface{} {
	return map[string]interface{}{
		"intent_id":        "reliability-rollback",
		"decision_id":      "rollback-bundle",
		"tool_call_id":     key,
		"tool_name":        toolName,
		"output_ref":       outputRef,
		"idempotency_key":  "idem-reliability-" + key,
		"write_generation": 1,
		"args":             args,
	}
}

func TestReliabilityTransactionBundleRollsBackEarlierWritesWhenLaterOperationFails(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	body := map[string]interface{}{
		"bundle_idempotency_key": "bundle-reliability-rollback",
		"staged_writes": []interface{}{
			reliabilityStagedWrite("post__machines", "machine", "$ref:machine", map[string]interface{}{
				"machine_id":        "M-TXN-ROLLBACK",
				"machine_name":      "Rollback Probe Machine",
				"machine_type":      "CNC",
				"capacity_per_hour": 12,
			}),
			reliabilityStagedWrite("post__machines_{id}_capabilities", "capability", "", map[string]interface{}{
				"id":                "$ref:machine",
				"step_id":           "STP-ROLLBACK",
				"efficiency_factor": 1.1,
			}),
			reliabilityStagedWrite("post__maintenance", "maintenance", "", map[string]interface{}{
				"machine_id":       "$ref:machine",
				"maintenance_type": "unsafe",
				"technician":       "Reliability",
				"description":      "should fail and roll back prior writes",
				"start_time":       "2026-06-02T01:00:00Z",
				"end_time":         "2026-06-02T02:00:00Z",
			}),
		},
	}

	w := reliabilityRequestJSONWithHeaders(
		r,
		"POST",
		"/api/v1/agent/transaction/commit",
		body,
		map[string]string{"Idempotency-Key": "bundle-reliability-rollback"},
	)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("commit should fail on invalid later operation: got %d, body: %s", w.Code, w.Body.String())
	}

	w = testutil.Request(r, "GET", "/api/v1/machines/M-TXN-ROLLBACK", nil)
	if w.Code != http.StatusNotFound {
		t.Fatalf("machine from failed bundle was committed: got %d, want 404, body: %s", w.Code, w.Body.String())
	}

	var machineCount, capabilityCount, maintenanceCount int64
	if err := db.Model(&domain.Machine{}).Where("machine_id = ?", "M-TXN-ROLLBACK").Count(&machineCount).Error; err != nil {
		t.Fatalf("count machine: %v", err)
	}
	if err := db.Model(&domain.MachineCapabilities{}).Where("machine_id = ?", "M-TXN-ROLLBACK").Count(&capabilityCount).Error; err != nil {
		t.Fatalf("count capabilities: %v", err)
	}
	if err := db.Model(&domain.MaintenanceRecords{}).Where("machine_id = ?", "M-TXN-ROLLBACK").Count(&maintenanceCount).Error; err != nil {
		t.Fatalf("count maintenance: %v", err)
	}
	if machineCount != 0 || capabilityCount != 0 || maintenanceCount != 0 {
		t.Fatalf("expected full rollback, got machines=%d capabilities=%d maintenance=%d", machineCount, capabilityCount, maintenanceCount)
	}
}
