package handler_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"emas/internal/domain"
	"emas/internal/router"
	"emas/internal/testutil"
)

func assertPDFResponse(t *testing.T, w *httptest.ResponseRecorder) {
	t.Helper()
	if w.Code != http.StatusOK {
		t.Fatalf("got status %d body %s", w.Code, w.Body.String())
	}
	if contentType := w.Header().Get("Content-Type"); !strings.HasPrefix(contentType, "application/pdf") {
		t.Fatalf("content type = %q, want application/pdf", contentType)
	}
	if disposition := w.Header().Get("Content-Disposition"); !strings.Contains(disposition, "inline;") || !strings.Contains(disposition, ".pdf") {
		t.Fatalf("content disposition = %q, want inline PDF filename", disposition)
	}
	if !bytes.HasPrefix(w.Body.Bytes(), []byte("%PDF")) {
		t.Fatalf("response body does not start with %%PDF")
	}
}

func TestReportsHandler_EndpointsReturnPDF(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	tests := []struct {
		name string
		path string
	}{
		{"production-output", "/api/v1/reports/production-output"},
		{"machine-utilization", "/api/v1/reports/machine-utilization"},
		{"job-completion", "/api/v1/reports/job-completion"},
		{"inventory-trends", "/api/v1/reports/inventory-trends"},
		{"quality-trends", "/api/v1/reports/quality-trends"},
		{"oee", "/api/v1/reports/oee"},
		{"bottlenecks", "/api/v1/reports/bottlenecks"},
		{"downtime", "/api/v1/reports/downtime"},
		{"maintenance-efficiency", "/api/v1/reports/maintenance-efficiency"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := testutil.Request(r, "GET", tt.path, nil)
			assertPDFResponse(t, w)
		})
	}
}

func TestReportsHandler_DownloadQueryReturnsAttachmentPDF(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/reports/machine-utilization?download=1", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("got status %d body %s", w.Code, w.Body.String())
	}
	if contentType := w.Header().Get("Content-Type"); !strings.HasPrefix(contentType, "application/pdf") {
		t.Fatalf("content type = %q, want application/pdf", contentType)
	}
	if disposition := w.Header().Get("Content-Disposition"); !strings.Contains(disposition, "attachment;") || !strings.Contains(disposition, ".pdf") {
		t.Fatalf("content disposition = %q, want attachment PDF filename", disposition)
	}
	if !bytes.HasPrefix(w.Body.Bytes(), []byte("%PDF")) {
		t.Fatalf("response body does not start with %%PDF")
	}
}

func TestReportsHandler_InvalidDateReturnsJSONError(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "GET", "/api/v1/reports/production-output?start=not-a-date", nil)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("got status %d body %s", w.Code, w.Body.String())
	}
	if contentType := w.Header().Get("Content-Type"); !strings.HasPrefix(contentType, "application/json") {
		t.Fatalf("content type = %q, want application/json", contentType)
	}
	success, _, errMsg := testutil.DecodeResponse(w)
	if success {
		t.Fatal("expected success false")
	}
	if !strings.Contains(errMsg, "invalid start") {
		t.Fatalf("error = %q, want invalid start", errMsg)
	}
}

func TestReportsHandler_ProductionAnalyticsReflectsRealRows(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	now := time.Now().UTC().Truncate(time.Second)
	start := now.Add(-2 * time.Hour)
	end := now.Add(-1 * time.Hour)
	downtimeMinutes := 15

	records := []interface{}{
		&domain.Machine{
			MachineID:       "M-REPORT-1",
			MachineName:     "Report Mill",
			MachineType:     "CNC",
			Status:          domain.MachineStatusRunning,
			CapacityPerHour: 120,
		},
		&domain.Job{
			JobID:             "JOB-REPORT-1",
			ProductID:         "PROD-REPORT-1",
			QuantityTotal:     100,
			QuantityCompleted: 0,
			Status:            domain.JobStatusRunning,
			Deadline:          now.Add(24 * time.Hour),
			CreatedAt:         now.Add(-24 * time.Hour),
			UpdatedAt:         now,
		},
		&domain.JobSteps{
			JobStepID:         "STEP-REPORT-1",
			JobID:             "JOB-REPORT-1",
			StepID:            "CUT",
			StepSequence:      1,
			QuantityTarget:    100,
			QuantityCompleted: 0,
			Status:            domain.JobStepStatusRunning,
		},
		&domain.JobStepScheduleSlots{
			SlotID:          "SLOT-REPORT-1",
			JobStepID:       "STEP-REPORT-1",
			MachineID:       "M-REPORT-1",
			ScheduledStart:  start,
			ScheduledEnd:    end,
			QuantityPlanned: 100,
			Status:          domain.SlotStatusCompleted,
		},
		&domain.ProductionLogs{
			ProductionID:     "PRODLOG-REPORT-1",
			SlotID:           "SLOT-REPORT-1",
			StartTime:        start,
			EndTime:          end,
			QuantityProduced: 90,
			QuantityScrap:    5,
			DowntimeMinutes:  &downtimeMinutes,
		},
		&domain.MachineDowntime{
			DowntimeID:      "DOWN-REPORT-1",
			MachineID:       "M-REPORT-1",
			JobStepSlotID:   "SLOT-REPORT-1",
			Cause:           "Tool change",
			StartTime:       start.Add(10 * time.Minute),
			EndTime:         start.Add(25 * time.Minute),
			DurationMinutes: 15,
		},
	}
	for _, record := range records {
		if err := db.Create(record).Error; err != nil {
			t.Fatalf("seed %T: %v", record, err)
		}
	}

	query := "?start=" + start.Add(-time.Hour).Format(time.RFC3339) + "&end=" + end.Add(time.Hour).Format(time.RFC3339)
	output := testutil.Request(r, "GET", "/api/v1/production-analytics/output"+query, nil)
	if output.Code != http.StatusOK {
		t.Fatalf("output status %d body %s", output.Code, output.Body.String())
	}
	var outputResp struct {
		Success bool `json:"success"`
		Data    []struct {
			MachineID        string `json:"machine_id"`
			QuantityProduced int    `json:"quantity_produced"`
			QuantityScrap    int    `json:"quantity_scrap"`
		} `json:"data"`
	}
	if err := json.Unmarshal(output.Body.Bytes(), &outputResp); err != nil {
		t.Fatalf("decode output: %v", err)
	}
	if !outputResp.Success || len(outputResp.Data) != 1 {
		t.Fatalf("unexpected output response: %+v", outputResp)
	}
	if got := outputResp.Data[0].QuantityProduced; got != 90 {
		t.Fatalf("quantity produced = %d, want 90", got)
	}
	if got := outputResp.Data[0].QuantityScrap; got != 5 {
		t.Fatalf("quantity scrap = %d, want 5", got)
	}

	downtime := testutil.Request(r, "GET", "/api/v1/production-analytics/downtime"+query, nil)
	if downtime.Code != http.StatusOK {
		t.Fatalf("downtime status %d body %s", downtime.Code, downtime.Body.String())
	}
	var downtimeResp struct {
		Success bool `json:"success"`
		Data    []struct {
			MachineID       string  `json:"machine_id"`
			Cause           string  `json:"cause"`
			DurationMinutes float64 `json:"duration_minutes"`
			OccurrenceCount int     `json:"occurrence_count"`
		} `json:"data"`
	}
	if err := json.Unmarshal(downtime.Body.Bytes(), &downtimeResp); err != nil {
		t.Fatalf("decode downtime: %v", err)
	}
	if !downtimeResp.Success || len(downtimeResp.Data) != 1 {
		t.Fatalf("unexpected downtime response: %+v", downtimeResp)
	}
	if got := downtimeResp.Data[0].DurationMinutes; got != 15 {
		t.Fatalf("downtime minutes = %.1f, want 15", got)
	}

	pdf := testutil.Request(r, "GET", "/api/v1/reports/downtime"+query, nil)
	assertPDFResponse(t, pdf)
}
