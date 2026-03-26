package handler_test

import (
	"encoding/json"
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestPredictiveHandler_HighRiskJobs(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/predictive/high-risk-jobs", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("HighRiskJobs: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, errMsg := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("HighRiskJobs: success false, error: %s", errMsg)
	}

	arr, ok := data.([]interface{})
	if !ok {
		t.Fatalf("HighRiskJobs: data not array, got %T", data)
	}
	if len(arr) < 2 {
		t.Errorf("HighRiskJobs: expected at least 2 items, got %d", len(arr))
	}
	for i, it := range arr {
		m, ok := it.(map[string]interface{})
		if !ok {
			t.Errorf("HighRiskJobs[%d]: not an object", i)
			continue
		}
		for _, k := range []string{"job_id", "machine_name", "issue", "risk_level"} {
			if _, ok := m[k]; !ok {
				t.Errorf("HighRiskJobs[%d]: missing %s", i, k)
			}
		}
	}
}

func TestPredictiveHandler_Recommendations(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/predictive/recommendations", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("Recommendations: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("Recommendations: success false")
	}
	arr, ok := data.([]interface{})
	if !ok {
		t.Fatalf("Recommendations: data not array, got %T", data)
	}
	if len(arr) < 1 {
		t.Error("Recommendations: expected at least 1 item")
	}
	for i, it := range arr {
		m, ok := it.(map[string]interface{})
		if !ok {
			continue
		}
		if _, ok := m["title"]; !ok {
			t.Errorf("Recommendations[%d]: missing title", i)
		}
		if _, ok := m["action"]; !ok {
			t.Errorf("Recommendations[%d]: missing action", i)
		}
	}
}

func TestPredictiveHandler_Forecast(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	tests := []struct {
		query   string
		wantLen int
	}{
		{"", 7},
		{"type=delays", 7},
		{"type=failures", 7},
	}
	for _, tt := range tests {
		path := "/api/v1/predictive/forecast"
		if tt.query != "" {
			path += "?" + tt.query
		}
		w := testutil.Request(r, "GET", path, nil)
		if w.Code != http.StatusOK {
			t.Fatalf("Forecast %s: got %d", tt.query, w.Code)
		}
		var resp struct {
			Success bool `json:"success"`
			Data    struct {
				Type string `json:"type"`
				Data []struct {
					Label string  `json:"label"`
					Value float64 `json:"value"`
				} `json:"data"`
			} `json:"data"`
		}
		if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
			t.Fatalf("Forecast: parse: %v", err)
		}
		if !resp.Success {
			t.Fatal("Forecast: success false")
		}
		if len(resp.Data.Data) < tt.wantLen {
			t.Errorf("Forecast %s: expected at least %d points, got %d", tt.query, tt.wantLen, len(resp.Data.Data))
		}
	}
}

func TestPredictiveHandler_Confidence(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/predictive/confidence", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("Confidence: got %d, body: %s", w.Code, w.Body.String())
	}
	var resp struct {
		Success bool `json:"success"`
		Data    struct {
			ConfidencePct float64 `json:"confidence_pct"`
			Model         string  `json:"model"`
			LastTrained   string  `json:"last_trained"`
		} `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("Confidence: parse: %v", err)
	}
	if !resp.Success {
		t.Fatal("Confidence: success false")
	}
	if resp.Data.ConfidencePct < 0 || resp.Data.ConfidencePct > 100 {
		t.Errorf("Confidence: confidence_pct %v should be 0-100", resp.Data.ConfidencePct)
	}
	if resp.Data.Model == "" {
		t.Error("Confidence: model should be non-empty")
	}
}
