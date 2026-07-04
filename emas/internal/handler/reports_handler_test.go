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

func TestReportsHandler_CanonicalSeedProvidesDefaultReportDataWithoutActiveReportJobs(t *testing.T) {
	db := testutil.NewTestDB(t)
	testutil.SeedCanonical(t, db)
	r := testutil.NewTestRouter(db, router.Setup)

	output := testutil.Request(r, "GET", "/api/v1/production-analytics/output", nil)
	if output.Code != http.StatusOK {
		t.Fatalf("default output status %d body %s", output.Code, output.Body.String())
	}
	var outputResp struct {
		Success bool `json:"success"`
		Data    []struct {
			JobID            string `json:"job_id"`
			QuantityProduced int    `json:"quantity_produced"`
		} `json:"data"`
	}
	if err := json.Unmarshal(output.Body.Bytes(), &outputResp); err != nil {
		t.Fatalf("decode output: %v", err)
	}
	if !outputResp.Success || len(outputResp.Data) == 0 {
		t.Fatalf("default analytics output should include report seed rows: %+v", outputResp)
	}

	pdf := testutil.Request(r, "GET", "/api/v1/reports/production-output", nil)
	assertPDFResponse(t, pdf)

	var activeReportSlots int64
	if err := db.Table("job_step_schedule_slots AS s").
		Joins("JOIN job_steps js ON js.job_step_id = s.job_step_id").
		Where("js.job_id LIKE ?", "JOB-RPT-%").
		Where("s.status IN ?", []string{domain.SlotStatusPlanned, domain.SlotStatusRunning, domain.SlotStatusPaused}).
		Count(&activeReportSlots).Error; err != nil {
		t.Fatalf("count active report slots: %v", err)
	}
	if activeReportSlots != 0 {
		t.Fatalf("active JOB-RPT slots = %d, want 0", activeReportSlots)
	}

	rangeStart := time.Now().UTC().Truncate(24*time.Hour).AddDate(0, 0, -8)
	rangeEnd := time.Now().UTC().Add(24 * time.Hour)
	query := "?start=" + rangeStart.Format(time.RFC3339) + "&end=" + rangeEnd.Format(time.RFC3339)

	summary := testutil.Request(r, "GET", "/api/v1/production-analytics/summary"+query, nil)
	if summary.Code != http.StatusOK {
		t.Fatalf("summary status %d body %s", summary.Code, summary.Body.String())
	}
	var summaryResp struct {
		Success bool `json:"success"`
		Data    struct {
			TotalJobs      int `json:"total_jobs"`
			CompletedJobs  int `json:"completed_jobs"`
			InProgressJobs int `json:"in_progress_jobs"`
		} `json:"data"`
	}
	if err := json.Unmarshal(summary.Body.Bytes(), &summaryResp); err != nil {
		t.Fatalf("decode summary: %v", err)
	}
	if !summaryResp.Success || summaryResp.Data.TotalJobs != 2 || summaryResp.Data.CompletedJobs != 2 || summaryResp.Data.InProgressJobs != 0 {
		t.Fatalf("recent report jobs summary = %+v, want 2 completed and 0 in-progress", summaryResp)
	}

	completion := testutil.Request(r, "GET", "/api/v1/production-analytics/job-completion"+query, nil)
	if completion.Code != http.StatusOK {
		t.Fatalf("completion status %d body %s", completion.Code, completion.Body.String())
	}
	var completionResp struct {
		Success bool `json:"success"`
		Data    []struct {
			JobID             string  `json:"job_id"`
			Status            string  `json:"status"`
			QuantityTotal     int     `json:"quantity_total"`
			QuantityCompleted int     `json:"quantity_completed"`
			CompletionPct     float64 `json:"completion_pct"`
		} `json:"data"`
	}
	if err := json.Unmarshal(completion.Body.Bytes(), &completionResp); err != nil {
		t.Fatalf("decode completion: %v", err)
	}
	if !completionResp.Success || len(completionResp.Data) != 2 {
		t.Fatalf("recent report job completion rows = %+v, want 2 job-level rows", completionResp)
	}
	for _, row := range completionResp.Data {
		if row.Status != domain.JobStatusCompleted || row.QuantityCompleted != row.QuantityTotal || row.CompletionPct != 100 {
			t.Fatalf("completion row = %+v, want completed job-level progress", row)
		}
	}

	var plannedSeedJobs int64
	if err := db.Model(&domain.Job{}).
		Where("job_id LIKE ? AND status = ?", "JOB-SEED-%", domain.JobStatusPlanned).
		Count(&plannedSeedJobs).Error; err != nil {
		t.Fatalf("count planned seed jobs: %v", err)
	}
	if plannedSeedJobs != 26 {
		t.Fatalf("planned JOB-SEED jobs = %d, want 26", plannedSeedJobs)
	}
}
