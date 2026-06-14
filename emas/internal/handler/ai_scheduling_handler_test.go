package handler_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"emas/internal/domain"
	"emas/internal/router"
	"emas/internal/testutil"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

func TestAISchedulingHandler_Features(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	testAISchedulingAssist(t, r)
	testAISchedulingDelayRiskAndExplanation(t, r)
	testAISchedulingProposal(t, r)
	testAISchedulingProposalLifecycle(t, r)
	testAISchedulingApplyProposal(t, r)
	testAISchedulingBatchProposals(t, r)
	testAISchedulingApplyReplenishmentBatchOnlyCreatesSubmittedRows(t, db, r)
	testAISchedulingGetProposal404(t, r)
	testAISchedulingSplitSuggestion(t, r)
	testAISchedulingMachineRanking(t, r)
	testAISchedulingBottleneckForecast(t, r)
	testAISchedulingMetrics(t, r)
	testAISchedulingApproveApply_InvalidBody(t, r)
	testAISchedulingVerifyOverlaps_InvalidProposalID(t, r)
	testAISchedulingApplyRollbackOnSplitOverflow(t, db, r)
	testAISchedulingApplyRepairsLegacySplitFallback(t, db, r)
	testAISchedulingProposalTrainingLineageLifecycle(t, db, r)
}

func testAISchedulingAssist(t *testing.T, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-AI", "product_name": "AI Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-AI", "product_id": "P-AI", "process_name": "AI Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-AI/steps", map[string]interface{}{
		"step_id": "STEP-AI", "step_name": "Assembly", "machine_type_required": "ASM",
		"allow_parallel_execution": true, "max_parallel_machines": 2, "min_split_qty": 5,
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-AI-1", "machine_name": "Assembly 1", "machine_type": "ASM", "capacity_per_hour": 40,
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-AI-2", "machine_name": "Assembly 2", "machine_type": "ASM", "capacity_per_hour": 35,
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-AI", "quantity_total": 20, "deadline": "2026-09-01T12:00:00Z",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create job: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "GET", "/api/v1/ai/scheduling/jobs/"+jobID+"/assist", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("assist: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("assist: success false")
	}
	payload := data.(map[string]interface{})
	if _, ok := payload["solver_preview"]; !ok {
		t.Fatal("expected solver_preview in assist response")
	}
	if _, ok := payload["explanation"]; !ok {
		t.Fatal("expected explanation in assist response")
	}
}

func testAISchedulingDelayRiskAndExplanation(t *testing.T, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-AI-RISK", "product_name": "AI Risk Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-AI-RISK", "product_id": "P-AI-RISK", "process_name": "AI Risk Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-AI-RISK/steps", map[string]interface{}{
		"step_id": "STEP-AI-RISK", "step_name": "Risk Step", "machine_type_required": "RISK",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-RISK", "machine_name": "Risk Machine", "machine_type": "RISK", "capacity_per_hour": 8,
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-AI-RISK", "quantity_total": 100, "deadline": time.Now().Add(-2 * time.Hour).UTC().Format(time.RFC3339),
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create risk job: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "GET", "/api/v1/ai/scheduling/jobs/"+jobID+"/delay-risk", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("delay risk: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("delay risk: success false")
	}
	payload := data.(map[string]interface{})
	if _, ok := payload["risk_score"]; !ok {
		t.Fatal("expected risk_score")
	}
	if _, ok := payload["reasons"]; !ok {
		t.Fatal("expected reasons")
	}

	w = testutil.Request(r, "GET", "/api/v1/ai/scheduling/jobs/"+jobID+"/explanation", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("explanation: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatal("explanation: success false")
	}
	payload = data.(map[string]interface{})
	if _, ok := payload["summary"]; !ok {
		t.Fatal("expected summary")
	}
	if _, ok := payload["recommended_actions"]; !ok {
		t.Fatal("expected recommended_actions")
	}
}

func testAISchedulingSplitSuggestion(t *testing.T, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-SPLIT-AI", "product_name": "Split Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-SPLIT-AI", "product_id": "P-SPLIT-AI", "process_name": "Split Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-SPLIT-AI/steps", map[string]interface{}{
		"step_id": "STEP-SPLIT-AI", "step_name": "Parallel Step", "machine_type_required": "PACK",
		"allow_parallel_execution": true, "max_parallel_machines": 3, "min_split_qty": 10,
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-PACK-1", "machine_name": "Pack 1", "machine_type": "PACK",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-PACK-2", "machine_name": "Pack 2", "machine_type": "PACK",
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-SPLIT-AI", "quantity_total": 40, "deadline": "2026-10-01T12:00:00Z",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create job: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)
	w = testutil.Request(r, "GET", "/api/v1/jobs/"+jobID+"/steps", nil)
	_, data, _ = testutil.DecodeResponse(w)
	jobStepID := data.([]interface{})[0].(map[string]interface{})["job_step_id"].(string)

	w = testutil.Request(r, "GET", "/api/v1/ai/scheduling/job-steps/"+jobStepID+"/split-suggestion", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("split suggestion: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("split suggestion: success false")
	}
	payload := data.(map[string]interface{})
	if payload["recommended_splits"].(float64) < 1 {
		t.Fatal("expected recommended_splits >= 1")
	}
}

func testAISchedulingMachineRanking(t *testing.T, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-RANK", "product_name": "Rank Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-RANK", "product_id": "P-RANK", "process_name": "Rank Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-RANK/steps", map[string]interface{}{
		"step_id": "STEP-RANK", "step_name": "Ranking Step", "machine_type_required": "RANK",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-RANK-1", "machine_name": "Rank 1", "machine_type": "RANK", "capacity_per_hour": 50,
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-RANK-2", "machine_name": "Rank 2", "machine_type": "RANK", "capacity_per_hour": 35,
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-RANK", "quantity_total": 30, "deadline": "2026-11-01T12:00:00Z",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create ranking job: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)
	w = testutil.Request(r, "GET", "/api/v1/jobs/"+jobID+"/steps", nil)
	_, data, _ = testutil.DecodeResponse(w)
	jobStepID := data.([]interface{})[0].(map[string]interface{})["job_step_id"].(string)

	w = testutil.Request(r, "GET", "/api/v1/ai/scheduling/job-steps/"+jobStepID+"/machine-ranking", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("machine ranking: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("machine ranking: success false")
	}
	payload := data.(map[string]interface{})
	candidates := payload["candidates"].([]interface{})
	if len(candidates) == 0 {
		t.Fatal("expected ranked candidates")
	}
}

func testAISchedulingProposal(t *testing.T, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-PROPOSAL", "product_name": "Proposal Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-PROPOSAL", "product_id": "P-PROPOSAL", "process_name": "Proposal Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-PROPOSAL/steps", map[string]interface{}{
		"step_id": "STEP-PROPOSAL", "step_name": "Proposal Step", "machine_type_required": "PROP", "allow_parallel_execution": true, "max_parallel_machines": 2, "min_split_qty": 5,
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-PROP-1", "machine_name": "Proposal 1", "machine_type": "PROP", "capacity_per_hour": 30,
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-PROP-2", "machine_name": "Proposal 2", "machine_type": "PROP", "capacity_per_hour": 25,
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-PROPOSAL", "quantity_total": 20, "deadline": "2026-11-05T12:00:00Z",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create proposal job: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "GET", "/api/v1/ai/scheduling/jobs/"+jobID+"/proposal", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("proposal: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("proposal: success false")
	}
	payload := data.(map[string]interface{})
	if _, ok := payload["proposed_slots"]; !ok {
		t.Fatal("expected proposed_slots")
	}
}

func testAISchedulingApplyProposal(t *testing.T, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-APPLY", "product_name": "Apply Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-APPLY", "product_id": "P-APPLY", "process_name": "Apply Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-APPLY/steps", map[string]interface{}{
		"step_id": "STEP-APPLY", "step_name": "Apply Step", "machine_type_required": "APPLY",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-APPLY", "machine_name": "Apply Machine", "machine_type": "APPLY", "capacity_per_hour": 20,
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-APPLY", "quantity_total": 10, "deadline": "2026-11-08T12:00:00Z",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create apply job: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/jobs/"+jobID+"/apply-proposal", nil, plannerAuthHeaders())
	if w.Code != http.StatusConflict {
		t.Fatalf("compat apply proposal should be blocked by default: got %d, body: %s", w.Code, w.Body.String())
	}
	success, _, errMsg := testutil.DecodeResponse(w)
	if success || errMsg == "" {
		t.Fatal("expected compatibility apply error response")
	}
}

func testAISchedulingBatchProposals(t *testing.T, r *gin.Engine) {
	// Setup: create product, process, machines, and unscheduled jobs
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-BATCH", "product_name": "Batch Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-BATCH", "product_id": "P-BATCH", "process_name": "Batch Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-BATCH/steps", map[string]interface{}{
		"step_id": "STEP-BATCH", "step_name": "Batch Step", "machine_type_required": "BAT",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-BAT-1", "machine_name": "Batch Machine", "machine_type": "BAT", "capacity_per_hour": 30,
	})

	// Create 3 unscheduled jobs (planned, no slots)
	w1 := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-BATCH", "quantity_total": 10, "deadline": "2026-12-15T12:00:00Z", "priority": "high",
	})
	if w1.Code != http.StatusCreated {
		t.Fatalf("create batch job 1: got %d, body: %s", w1.Code, w1.Body.String())
	}
	_, d1, _ := testutil.DecodeResponse(w1)
	job1 := d1.(map[string]interface{})["job_id"].(string)

	w2 := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-BATCH", "quantity_total": 20, "deadline": "2026-12-10T12:00:00Z", "priority": "medium",
	})
	if w2.Code != http.StatusCreated {
		t.Fatalf("create batch job 2: got %d, body: %s", w2.Code, w2.Body.String())
	}
	_, d2, _ := testutil.DecodeResponse(w2)
	job2 := d2.(map[string]interface{})["job_id"].(string)

	w3 := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-BATCH", "quantity_total": 15, "deadline": "2026-12-20T12:00:00Z", "priority": "low",
	})
	if w3.Code != http.StatusCreated {
		t.Fatalf("create batch job 3: got %d, body: %s", w3.Code, w3.Body.String())
	}
	_, d3, _ := testutil.DecodeResponse(w3)
	job3 := d3.(map[string]interface{})["job_id"].(string)

	// Scope: all_unscheduled
	w := testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"scope": "all_unscheduled",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("batch scope all_unscheduled: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("batch scope: success false")
	}
	payload := data.(map[string]interface{})
	proposals := payload["proposals"].([]interface{})
	summary := payload["summary"].(map[string]interface{})
	gen := int(summary["generated"].(float64))
	if gen < 1 {
		t.Fatalf("expected summary.generated >= 1, got %d", gen)
	}
	if len(proposals) != gen {
		t.Fatalf("proposals length %d != summary.generated %d", len(proposals), gen)
	}

	// Job IDs explicit
	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"job_ids": []string{job2, job3},
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("batch job_ids: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatal("batch job_ids: success false")
	}
	payload = data.(map[string]interface{})
	proposals = payload["proposals"].([]interface{})
	jobIDs := make([]string, 0, len(proposals))
	for _, p := range proposals {
		jobIDs = append(jobIDs, p.(map[string]interface{})["job_id"].(string))
	}
	if len(jobIDs) < 1 {
		t.Fatal("expected at least 1 proposal for explicit job_ids")
	}
	found := false
	for _, id := range jobIDs {
		if id == job2 || id == job3 {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("expected proposals for job2 or job3, got %v", jobIDs)
	}

	// Order by EDD
	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"job_ids":  []string{job1, job2, job3},
		"order_by": "edd",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("batch order_by edd: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatal("batch order_by edd: success false")
	}

	// Order by FIFO
	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"job_ids":  []string{job1, job2, job3},
		"order_by": "fifo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("batch order_by fifo: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatal("batch order_by fifo: success false")
	}

	// Validation: missing job_ids and scope
	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{}, plannerAuthHeaders())
	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for missing scope/job_ids, got %d body: %s", w.Code, w.Body.String())
	}
	_, _, errMsg := testutil.DecodeResponse(w)
	if errMsg == "" {
		t.Fatal("expected error message for validation")
	}

	// Validation: empty job_ids and no scope
	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"job_ids": []string{},
	}, plannerAuthHeaders())
	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for empty job_ids and no scope, got %d body: %s", w.Code, w.Body.String())
	}
}

func testAISchedulingApplyReplenishmentBatchOnlyCreatesSubmittedRows(t *testing.T, db *gorm.DB, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-BATCH-PLAN", "product_name": "Batch Planned Product",
	})
	testutil.Request(r, "POST", "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-BATCH-APPLY", "material_name": "Batch Apply Material", "unit": "pcs",
		"current_stock": 0, "min_stock": 0, "reorder_level": 1, "storage_location": "TEST",
	})

	arriveAt := time.Now().UTC().Add(48 * time.Hour).Format(time.RFC3339)
	w := testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/apply-replenishment-batch", map[string]interface{}{
		"suggestions": []map[string]interface{}{
			{
				"material_id": "MAT-BATCH-APPLY",
				"quantity":    12,
				"arrive_at":   arriveAt,
			},
		},
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("apply material-only batch replenishment: got %d, body: %s", w.Code, w.Body.String())
	}

	var materialArrivalCount int64
	if err := db.Model(&domain.InventoryExpectedArrival{}).Where("material_id = ?", "MAT-BATCH-APPLY").Count(&materialArrivalCount).Error; err != nil {
		t.Fatalf("count material arrivals: %v", err)
	}
	if materialArrivalCount != 1 {
		t.Fatalf("expected one material expected arrival, got %d", materialArrivalCount)
	}
	var plannedProductCount int64
	if err := db.Model(&domain.ProductInventory{}).Where("product_id = ? AND status = ?", "P-BATCH-PLAN", domain.ProductInventoryStatusPlanned).Count(&plannedProductCount).Error; err != nil {
		t.Fatalf("count planned product inventory before product row: %v", err)
	}
	if plannedProductCount != 0 {
		t.Fatalf("expected no planned product inventory without submitted product row, got %d", plannedProductCount)
	}

	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/apply-replenishment-batch", map[string]interface{}{
		"suggestions": []map[string]interface{}{
			{
				"option_type": "schedule_production",
				"material_id": "P-BATCH-PLAN",
				"quantity":    5,
				"arrive_at":   time.Now().UTC().Add(72 * time.Hour).Format(time.RFC3339),
			},
		},
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("apply unsupported planned-product batch row: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	if body, ok := data.(map[string]interface{}); ok {
		if got, _ := body["unsupported_schedule_production_rows"].(float64); int(got) != 1 {
			t.Fatalf("unsupported_schedule_production_rows=%v, want 1; body=%#v", body["unsupported_schedule_production_rows"], body)
		}
	}

	if err := db.Model(&domain.ProductInventory{}).Where("product_id = ? AND status = ?", "P-BATCH-PLAN", domain.ProductInventoryStatusPlanned).Count(&plannedProductCount).Error; err != nil {
		t.Fatalf("count planned product inventory after product row: %v", err)
	}
	if plannedProductCount != 0 {
		t.Fatalf("schedule_production rows must not create planned product inventory, got %d", plannedProductCount)
	}
}

func testAISchedulingProposalLifecycle(t *testing.T, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-LIFE", "product_name": "Lifecycle Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-LIFE", "product_id": "P-LIFE", "process_name": "Lifecycle Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-LIFE/steps", map[string]interface{}{
		"step_id": "STEP-LIFE", "step_name": "Lifecycle Step", "machine_type_required": "LIFE",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-LIFE", "machine_name": "Lifecycle Machine", "machine_type": "LIFE", "capacity_per_hour": 22,
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-LIFE", "quantity_total": 8, "deadline": "2026-11-12T12:00:00Z",
	})
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/jobs/"+jobID+"/proposals", nil)
	if w.Code != http.StatusCreated {
		t.Fatalf("generate proposal: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("generate proposal: success false")
	}
	proposalID := data.(map[string]interface{})["proposal_id"].(string)

	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/apply", map[string]interface{}{
		"idempotency_key": "LIFE-DRAFT-BLOCK",
	}, plannerAuthHeaders())
	if w.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected draft apply to be blocked, got %d body: %s", w.Code, w.Body.String())
	}

	w = testutil.Request(r, "GET", "/api/v1/ai/scheduling/jobs/"+jobID+"/proposals", nil)
	success, data, _ = testutil.DecodeResponse(w)
	if !success || len(data.([]interface{})) == 0 {
		t.Fatal("expected proposal list for job")
	}

	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/approve", map[string]interface{}{
		"notes": "reviewed",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("approve proposal: got %d, body: %s", w.Code, w.Body.String())
	}

	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/apply", map[string]interface{}{
		"idempotency_key": "LIFE-KEY-1",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("apply proposal by id: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatal("apply proposal by id: success false")
	}
	payload := data.(map[string]interface{})
	if payload["proposal_id"] != proposalID {
		t.Fatalf("expected applied proposal_id %s, got %v", proposalID, payload["proposal_id"])
	}

	w = testutil.Request(r, "GET", "/api/v1/ai/scheduling/proposals/"+proposalID, nil)
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatal("get proposal by id: success false")
	}
	payload = data.(map[string]interface{})
	if payload["status"] != "applied" {
		t.Fatalf("expected applied status, got %v", payload["status"])
	}

	// Idempotency: apply with same key again returns 200
	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/apply", map[string]interface{}{
		"idempotency_key": "LIFE-KEY-1",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("idempotent apply: expected 200, got %d body: %s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatal("idempotent apply: success false")
	}
	payload = data.(map[string]interface{})
	if payload["message"] == "" {
		t.Fatal("expected idempotency message in response")
	}
}

func testAISchedulingProposalTrainingLineageLifecycle(t *testing.T, db *gorm.DB, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-ML-LINEAGE", "product_name": "ML Lineage Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-ML-LINEAGE", "product_id": "P-ML-LINEAGE", "process_name": "ML Lineage Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-ML-LINEAGE/steps", map[string]interface{}{
		"step_id": "STEP-ML-LINEAGE", "step_name": "ML Lineage Step", "machine_type_required": "MLL",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-ML-LINEAGE", "machine_name": "ML Lineage Machine", "machine_type": "MLL", "capacity_per_hour": 16,
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-ML-LINEAGE", "quantity_total": 9, "deadline": "2026-11-15T12:00:00Z",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create ml lineage job: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/jobs/"+jobID+"/proposals", nil)
	if w.Code != http.StatusCreated {
		t.Fatalf("generate ml lineage proposal: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("generate ml lineage proposal: success false")
	}
	proposalID := data.(map[string]interface{})["proposal_id"].(string)

	var draftRows []domain.MLTrainingEvent
	if err := db.Where("proposal_id = ?", proposalID).Order("scheduled_start").Find(&draftRows).Error; err != nil {
		t.Fatalf("load ml training draft rows: %v", err)
	}
	if len(draftRows) == 0 {
		t.Fatal("expected proposal generation to create draft ml training rows")
	}
	for _, row := range draftRows {
		if row.LineageID == "" {
			t.Fatal("expected proposal draft row to have lineage_id")
		}
		if row.SlotID != nil && *row.SlotID != "" {
			t.Fatal("expected proposal draft row to have empty slot_id before apply")
		}
	}

	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/approve", map[string]interface{}{
		"notes": "ml lineage approval",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("approve ml lineage proposal: got %d, body: %s", w.Code, w.Body.String())
	}
	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/apply", map[string]interface{}{
		"idempotency_key": "ML-LINEAGE-APPLY",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("apply ml lineage proposal: got %d, body: %s", w.Code, w.Body.String())
	}

	var appliedRows []domain.MLTrainingEvent
	if err := db.Where("proposal_id = ?", proposalID).Order("scheduled_start").Find(&appliedRows).Error; err != nil {
		t.Fatalf("load ml training applied rows: %v", err)
	}
	if len(appliedRows) != len(draftRows) {
		t.Fatalf("expected applied ml training row count %d, got %d", len(draftRows), len(appliedRows))
	}
	for _, row := range appliedRows {
		if row.SlotID == nil || *row.SlotID == "" {
			t.Fatal("expected applied ml training row to be linked to slot_id")
		}
	}
}

func testAISchedulingGetProposal404(t *testing.T, r *gin.Engine) {
	w := testutil.Request(r, "GET", "/api/v1/ai/scheduling/proposals/AIPROP-INVALID-999", nil)
	if w.Code != http.StatusNotFound {
		t.Fatalf("get invalid proposal: expected 404, got %d body: %s", w.Code, w.Body.String())
	}
}

func testAISchedulingBottleneckForecast(t *testing.T, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-BOT", "machine_name": "Bottleneck Machine", "machine_type": "BOT",
	})
	w := testutil.Request(r, "GET", "/api/v1/ai/scheduling/bottleneck-forecast?days_ahead=5", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("bottleneck forecast: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("bottleneck forecast: success false")
	}
	payload := data.(map[string]interface{})
	if payload["days_ahead"].(float64) != 5 {
		t.Fatal("expected days_ahead to be 5")
	}
	if _, ok := payload["entries"]; !ok {
		t.Fatal("expected entries in bottleneck forecast")
	}
}

func testAISchedulingMetrics(t *testing.T, r *gin.Engine) {
	w := testutil.Request(r, "GET", "/api/v1/ai/metrics", nil)
	if w.Code != http.StatusOK {
		t.Fatalf("ai metrics: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("ai metrics: success false")
	}
	payload := data.(map[string]interface{})
	if _, ok := payload["proposal_generated"]; !ok {
		t.Fatal("expected proposal_generated metric")
	}
	if _, ok := payload["acceptance_rate"]; !ok {
		t.Fatal("expected acceptance_rate metric")
	}
	if _, ok := payload["rollout_state"]; !ok {
		t.Fatal("expected rollout_state metric")
	}
}

func testAISchedulingApproveApply_InvalidBody(t *testing.T, r *gin.Engine) {
	// Invalid JSON body should now fail fast instead of silently defaulting.
	rawRequest := func(method, path, body, contentType string) *httptest.ResponseRecorder {
		req, _ := http.NewRequest(method, path, bytes.NewBufferString(body))
		req.Header.Set("Content-Type", contentType)
		for key, value := range plannerAuthHeaders() {
			req.Header.Set(key, value)
		}
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		return w
	}
	w := rawRequest("POST", "/api/v1/ai/scheduling/proposals/AIPROP-INVALID/approve", "{invalid-json", "application/json")
	if w.Code != http.StatusBadRequest {
		t.Fatalf("approve invalid body: expected 400, got %d body: %s", w.Code, w.Body.String())
	}
	w = rawRequest("POST", "/api/v1/ai/scheduling/proposals/AIPROP-INVALID/apply", "{invalid-json", "application/json")
	if w.Code != http.StatusBadRequest {
		t.Fatalf("apply invalid body: expected 400, got %d body: %s", w.Code, w.Body.String())
	}
}

func testAISchedulingVerifyOverlaps_InvalidProposalID(t *testing.T, r *gin.Engine) {
	w := testutil.Request(r, "POST", "/api/v1/ai/scheduling/verify-overlaps", map[string]interface{}{
		"scope":        "proposals",
		"proposal_ids": []string{"AIPROP-DOES-NOT-EXIST"},
	})
	if w.Code != http.StatusBadRequest {
		t.Fatalf("verify-overlaps invalid proposal id: expected 400, got %d body: %s", w.Code, w.Body.String())
	}
}

func testAISchedulingApplyRollbackOnSplitOverflow(t *testing.T, db *gorm.DB, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-ROLLBACK", "product_name": "Rollback Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-ROLLBACK", "product_id": "P-ROLLBACK", "process_name": "Rollback Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-ROLLBACK/steps", map[string]interface{}{
		"step_id": "STEP-ROLLBACK", "step_name": "Parallel Step", "machine_type_required": "RB",
		"allow_parallel_execution": true, "max_parallel_machines": 2, "min_split_qty": 1,
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-RB-1", "machine_name": "Rollback Machine 1", "machine_type": "RB", "capacity_per_hour": 20,
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-RB-2", "machine_name": "Rollback Machine 2", "machine_type": "RB", "capacity_per_hour": 20,
	})

	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-ROLLBACK", "quantity_total": 10, "deadline": "2026-11-12T12:00:00Z",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create rollback job: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/jobs/"+jobID+"/proposals", nil)
	if w.Code != http.StatusCreated {
		t.Fatalf("generate rollback proposal: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("generate rollback proposal: success false")
	}
	proposalID := data.(map[string]interface{})["proposal_id"].(string)

	var record domain.AIProposal
	if err := db.First(&record, "proposal_id = ?", proposalID).Error; err != nil {
		t.Fatalf("load rollback proposal: %v", err)
	}

	var proposal map[string]interface{}
	if err := json.Unmarshal([]byte(record.ProposalJSON), &proposal); err != nil {
		t.Fatalf("decode rollback proposal json: %v", err)
	}
	slots, ok := proposal["proposed_slots"].([]interface{})
	if !ok || len(slots) == 0 {
		t.Fatal("expected at least one proposed slot to mutate")
	}
	slot0, ok := slots[0].(map[string]interface{})
	if !ok {
		t.Fatal("expected first proposed slot object")
	}
	slot0["machine_id"] = "M-RB-1"
	slot0["machine_name"] = "Rollback Machine 1"
	slot0["quantity_planned"] = float64(6)
	slot0["allocation_percent"] = float64(60)
	slot0["is_parallel"] = true
	slot0["batch_sequence"] = float64(1)
	slot1 := map[string]interface{}{}
	for k, v := range slot0 {
		slot1[k] = v
	}
	slot1["machine_id"] = "M-RB-2"
	slot1["machine_name"] = "Rollback Machine 2"
	slot1["quantity_planned"] = float64(5)
	slot1["allocation_percent"] = float64(50)
	slot1["batch_sequence"] = float64(2)
	proposal["proposed_slots"] = []interface{}{slot0, slot1}
	raw, err := json.Marshal(proposal)
	if err != nil {
		t.Fatalf("encode rollback proposal json: %v", err)
	}
	record.ProposalJSON = string(raw)
	if err := db.Save(&record).Error; err != nil {
		t.Fatalf("save mutated rollback proposal: %v", err)
	}

	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/approve", map[string]interface{}{
		"notes": "rollback test approval",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("approve rollback proposal: got %d, body: %s", w.Code, w.Body.String())
	}

	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/apply", map[string]interface{}{
		"idempotency_key": "ROLLBACK-OVERFLOW",
	}, plannerAuthHeaders())
	if w.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected invalid split apply failure, got %d body: %s", w.Code, w.Body.String())
	}

	var slotCount int64
	if err := db.Table("job_step_schedule_slots").Where("proposal_id = ?", proposalID).Count(&slotCount).Error; err != nil {
		t.Fatalf("count rollback slots: %v", err)
	}
	if slotCount != 0 {
		t.Fatalf("expected no slots after failed apply rollback, found %d", slotCount)
	}
}

func testAISchedulingApplyRepairsLegacySplitFallback(t *testing.T, db *gorm.DB, r *gin.Engine) {
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-LEGACY", "product_name": "Legacy Split Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-LEGACY", "product_id": "P-LEGACY", "process_name": "Legacy Split Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-LEGACY/steps", map[string]interface{}{
		"step_id": "STEP-LEGACY", "step_name": "Legacy Step", "machine_type_required": "LEG",
		"allow_parallel_execution": true, "max_parallel_machines": 2, "min_split_qty": 10,
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-LEG-1", "machine_name": "Legacy Machine 1", "machine_type": "LEG", "capacity_per_hour": 20,
	})

	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-LEGACY", "quantity_total": 10, "deadline": "2026-11-13T12:00:00Z",
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create legacy job: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/jobs/"+jobID+"/proposals", nil)
	if w.Code != http.StatusCreated {
		t.Fatalf("generate legacy proposal: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("generate legacy proposal: success false")
	}
	proposalID := data.(map[string]interface{})["proposal_id"].(string)

	var record domain.AIProposal
	if err := db.First(&record, "proposal_id = ?", proposalID).Error; err != nil {
		t.Fatalf("load legacy proposal: %v", err)
	}

	var proposal map[string]interface{}
	if err := json.Unmarshal([]byte(record.ProposalJSON), &proposal); err != nil {
		t.Fatalf("decode legacy proposal json: %v", err)
	}
	slots, ok := proposal["proposed_slots"].([]interface{})
	if !ok || len(slots) == 0 {
		t.Fatal("expected at least one proposed slot to mutate for legacy repair")
	}
	slot0, ok := slots[0].(map[string]interface{})
	if !ok {
		t.Fatal("expected first legacy slot object")
	}
	startRaw, _ := slot0["scheduled_start"].(string)
	endRaw, _ := slot0["scheduled_end"].(string)
	start, err := time.Parse(time.RFC3339, startRaw)
	if err != nil {
		t.Fatalf("parse legacy slot start: %v", err)
	}
	end, err := time.Parse(time.RFC3339, endRaw)
	if err != nil {
		t.Fatalf("parse legacy slot end: %v", err)
	}
	mid := start.Add(end.Sub(start) / 2)
	slot0["scheduled_end"] = mid.Format(time.RFC3339)
	slot0["quantity_planned"] = float64(10)
	slot0["allocation_percent"] = float64(100)
	slot0["is_parallel"] = false
	slot0["batch_sequence"] = float64(1)
	slot1 := map[string]interface{}{}
	for k, v := range slot0 {
		slot1[k] = v
	}
	slot1["scheduled_start"] = mid.Format(time.RFC3339)
	slot1["scheduled_end"] = end.Format(time.RFC3339)
	slot1["quantity_planned"] = float64(10)
	slot1["allocation_percent"] = float64(100)
	slot1["batch_sequence"] = float64(2)
	proposal["proposed_slots"] = []interface{}{slot0, slot1}
	raw, err := json.Marshal(proposal)
	if err != nil {
		t.Fatalf("encode legacy proposal json: %v", err)
	}
	record.ProposalJSON = string(raw)
	if err := db.Save(&record).Error; err != nil {
		t.Fatalf("save legacy proposal: %v", err)
	}

	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/approve", map[string]interface{}{
		"notes": "legacy repair approval",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("approve legacy proposal: got %d, body: %s", w.Code, w.Body.String())
	}

	w = testutil.RequestWithHeaders(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/apply", map[string]interface{}{
		"idempotency_key": "LEGACY-SPLIT-REPAIR",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("apply legacy proposal: got %d, body: %s", w.Code, w.Body.String())
	}

	var rows []struct {
		QuantityPlanned int `gorm:"column:quantity_planned"`
	}
	if err := db.Table("job_step_schedule_slots").Select("quantity_planned").Where("proposal_id = ?", proposalID).Find(&rows).Error; err != nil {
		t.Fatalf("load legacy applied slots: %v", err)
	}
	if len(rows) != 2 {
		t.Fatalf("expected 2 repaired applied slots, found %d", len(rows))
	}
	total := 0
	for _, row := range rows {
		total += row.QuantityPlanned
	}
	if total != 10 {
		t.Fatalf("expected repaired applied quantity total 10, got %d", total)
	}
}
