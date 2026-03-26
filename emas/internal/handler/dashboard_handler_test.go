package handler_test

import (
	"encoding/json"
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestDashboardHandler_GetKPIs(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/dashboard/kpis", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("GetKPIs: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, errMsg := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("GetKPIs: success false, error: %s", errMsg)
	}

	m, ok := data.(map[string]interface{})
	if !ok {
		t.Fatalf("GetKPIs: data not a map, got %T", data)
	}
	for _, key := range []string{"oee_pct", "production_units", "downtime_hrs", "utilization_pct"} {
		if _, ok := m[key]; !ok {
			t.Errorf("GetKPIs: missing key %s", key)
		}
	}
	if oee, ok := m["oee_pct"].(float64); ok && oee < 0 {
		t.Errorf("GetKPIs: oee_pct should be non-negative, got %v", oee)
	}
}

func TestDashboardHandler_GetAlerts(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	// Without status filter
	w := testutil.Request(r, "GET", "/api/v1/alerts", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("GetAlerts: got %d, body: %s", w.Code, w.Body.String())
	}
	success, _, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("GetAlerts: success false")
	}

	// With status=active
	w = testutil.Request(r, "GET", "/api/v1/alerts?status=active", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("GetAlerts status=active: got %d", w.Code)
	}
	var resp struct {
		Success bool `json:"success"`
		Data    []struct {
			Type  string `json:"type"`
			Title string `json:"title"`
			Time  string `json:"time"`
		} `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("GetAlerts: parse json: %v", err)
	}
	if !resp.Success {
		t.Fatal("GetAlerts: success false")
	}
	// Data may be empty array or populated; either is valid
	if resp.Data == nil {
		t.Error("GetAlerts: data should be array (possibly empty)")
	}
}
