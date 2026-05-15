package handler_test

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"emas/internal/router"
	"emas/internal/testutil"

	"github.com/gin-gonic/gin"
)

const schedulingSmokeBudget = 20 * time.Second

func TestAISchedulingPerformanceSmokeBatchProposalsAndRescheduleAll(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping scheduling performance smoke test in short mode")
	}
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "30000")

	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	jobIDs := seedSchedulingSmokeJobs(t, r, 4)
	headers := map[string]string{
		"X-User-Id":   "qa-smoke",
		"X-User-Role": "planner",
	}

	started := time.Now()
	w := testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"job_ids":  jobIDs,
		"order_by": "edd",
	}, headers)
	elapsed := time.Since(started)
	if w.Code != http.StatusOK {
		t.Fatalf("batch-proposals status = %d, want 200, body=%s", w.Code, w.Body.String())
	}
	assertSchedulingSmokeGenerated(t, w, "batch-proposals")
	if elapsed > schedulingSmokeBudget {
		t.Fatalf("batch-proposals elapsed = %s, budget = %s", elapsed, schedulingSmokeBudget)
	}
	t.Logf("batch-proposals smoke elapsed=%s jobs=%d", elapsed, len(jobIDs))

	started = time.Now()
	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/reschedule-all", map[string]interface{}{
		"order_by": "edd",
		"dry_run":  true,
	}, headers)
	elapsed = time.Since(started)
	if w.Code != http.StatusOK {
		t.Fatalf("reschedule-all status = %d, want 200, body=%s", w.Code, w.Body.String())
	}
	assertSchedulingSmokeGenerated(t, w, "reschedule-all dry_run")
	if elapsed > schedulingSmokeBudget {
		t.Fatalf("reschedule-all elapsed = %s, budget = %s", elapsed, schedulingSmokeBudget)
	}
	t.Logf("reschedule-all dry_run smoke elapsed=%s jobs=%d", elapsed, len(jobIDs))
}

func seedSchedulingSmokeJobs(t *testing.T, r *gin.Engine, count int) []string {
	t.Helper()
	testutil.Request(r, http.MethodPost, "/api/v1/products", map[string]interface{}{
		"product_id":   "P-PERF",
		"product_name": "Performance Smoke Product",
	})
	testutil.Request(r, http.MethodPost, "/api/v1/processes", map[string]interface{}{
		"process_id":   "PRC-PERF",
		"product_id":   "P-PERF",
		"process_name": "Performance Smoke Process",
	})
	testutil.Request(r, http.MethodPost, "/api/v1/processes/PRC-PERF/steps", map[string]interface{}{
		"step_id":               "STEP-PERF",
		"step_name":             "Performance Step",
		"machine_type_required": "PERF",
		"max_parallel_machines": 2,
	})
	for i := 1; i <= 2; i++ {
		testutil.Request(r, http.MethodPost, "/api/v1/machines", map[string]interface{}{
			"machine_id":         fmt.Sprintf("M-PERF-%d", i),
			"machine_name":       fmt.Sprintf("Performance Machine %d", i),
			"machine_type":       "PERF",
			"capacity_per_hour":  60,
			"efficiency_factor":  1.0,
			"utilization_target": 0.8,
		})
	}

	jobIDs := make([]string, 0, count)
	for i := 1; i <= count; i++ {
		w := testutil.Request(r, http.MethodPost, "/api/v1/jobs", map[string]interface{}{
			"product_id":      "P-PERF",
			"quantity_total":  10 + i,
			"deadline":        time.Now().UTC().Add(time.Duration(24+i) * time.Hour).Format(time.RFC3339),
			"priority":        "medium",
			"customer_order":  fmt.Sprintf("PERF-%d", i),
			"notes":           "scheduling performance smoke",
			"allow_auto_plan": true,
		})
		if w.Code != http.StatusCreated {
			t.Fatalf("create smoke job %d status = %d, body=%s", i, w.Code, w.Body.String())
		}
		_, data, _ := testutil.DecodeResponse(w)
		jobIDs = append(jobIDs, data.(map[string]interface{})["job_id"].(string))
	}
	return jobIDs
}

func assertSchedulingSmokeGenerated(t *testing.T, w *httptest.ResponseRecorder, name string) {
	t.Helper()
	success, data, errMsg := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("%s response success=false error=%q body=%s", name, errMsg, w.Body.String())
	}
	payload, ok := data.(map[string]interface{})
	if !ok {
		t.Fatalf("%s data shape = %T, want object", name, data)
	}
	summary, ok := payload["summary"].(map[string]interface{})
	if !ok {
		t.Fatalf("%s summary shape = %T, want object", name, payload["summary"])
	}
	if generated, _ := summary["generated"].(float64); generated < 1 {
		t.Fatalf("%s summary.generated = %v, want >= 1", name, summary["generated"])
	}
}
