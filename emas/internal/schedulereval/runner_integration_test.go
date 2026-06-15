package schedulereval_test

import (
	"fmt"
	"net/http"
	"testing"
	"time"

	"emas/internal/router"
	"emas/internal/schedulereval"
	"emas/internal/service"
	"emas/internal/testutil"

	"github.com/gin-gonic/gin"
)

func TestHTTPRunnerNoShortageControlHasNoHardFailures(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "60000")

	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	seedNoShortageControl(t, r)

	runner := schedulereval.HTTPRunner{Handler: r, OrderBy: "epo", Headers: plannerHeaders()}
	score, err := runner.RunScorecard(t.Context(), schedulereval.RunRequest{
		ScenarioID: schedulereval.ScenarioNoShortageControl,
		Endpoint:   schedulereval.EndpointBatchProposals,
		DryRun:     true,
	}, schedulereval.EvaluateOptions{})
	if err != nil {
		t.Fatalf("run no shortage scorecard: %v", err)
	}

	if len(score.Failures) > 0 {
		t.Fatalf("unexpected evaluator failures: %#v", score.Failures)
	}
	if score.Feasibility.InfeasibleJobs != 0 {
		t.Fatalf("infeasible jobs=%d, want 0; score=%#v", score.Feasibility.InfeasibleJobs, score)
	}
	if score.Material.AggregateReplenishmentCount != 0 {
		t.Fatalf("aggregate material rows=%d, want 0", score.Material.AggregateReplenishmentCount)
	}
}

func TestHTTPRunnerMaterialShortageAndOneShotResolution(t *testing.T) {
	if testing.Short() {
		t.Skip("scheduler integration test can take several seconds")
	}
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "180000")

	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	seedDelayedAndStarvedMaterialFixture(t, r)

	runner := schedulereval.HTTPRunner{Handler: r, OrderBy: "epo", Headers: plannerHeaders()}
	initial, err := runner.RunScorecard(t.Context(), schedulereval.RunRequest{
		ScenarioID:              schedulereval.ScenarioTrueMaterialShortage,
		Endpoint:                schedulereval.EndpointBatchProposals,
		IncludeInventoryActions: true,
		DryRun:                  true,
	}, schedulereval.EvaluateOptions{})
	if err != nil {
		t.Fatalf("run initial material shortage scorecard: %v", err)
	}
	if len(initial.Failures) > 0 {
		t.Fatalf("initial material shortage scorecard hard failures: %#v", initial.Failures)
	}
	if initial.Feasibility.InfeasibleJobs != 1 {
		t.Fatalf("initial infeasible jobs=%d, want 1", initial.Feasibility.InfeasibleJobs)
	}
	if initial.Material.AggregateReplenishmentCount == 0 {
		t.Fatalf("initial score should expose aggregate material rows")
	}

	final, err := runner.RunOneShotResolution(t.Context(), schedulereval.RunRequest{
		ScenarioID:              schedulereval.ScenarioOneShotResolution,
		IncludeInventoryActions: true,
		DryRun:                  true,
	}, schedulereval.EvaluateOptions{})
	if err != nil {
		t.Fatalf("run one-shot scorecard: %v", err)
	}
	if len(final.Failures) > 0 {
		t.Fatalf("one-shot scorecard hard failures: %#v", final.Failures)
	}
	if final.Feasibility.InfeasibleJobs != 0 {
		t.Fatalf("one-shot infeasible jobs=%d, want 0", final.Feasibility.InfeasibleJobs)
	}
	if final.Material.AggregateReplenishmentCount != 0 {
		t.Fatalf("one-shot aggregate rows=%d, want 0; materials=%v", final.Material.AggregateReplenishmentCount, final.Material.AggregateMaterialIDs)
	}
}

func TestHTTPRunnerDelayedMaterialWaitsInsteadOfFalseShortage(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "60000")

	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	arrivalAt, jobID := seedDelayedMaterialOnlyFixture(t, r)

	runner := schedulereval.HTTPRunner{Handler: r, OrderBy: "epo", Headers: plannerHeaders()}
	result, err := runner.Run(t.Context(), schedulereval.RunRequest{
		ScenarioID:              schedulereval.ScenarioDelayedMaterialWait,
		Endpoint:                schedulereval.EndpointBatchProposals,
		IncludeInventoryActions: true,
		DryRun:                  true,
	})
	if err != nil {
		t.Fatalf("run delayed material scenario: %v", err)
	}
	score := schedulereval.Evaluate(result, schedulereval.EvaluateOptions{})
	if len(score.Failures) > 0 {
		t.Fatalf("delayed material scorecard hard failures: %#v", score.Failures)
	}
	if score.Feasibility.InfeasibleJobs != 0 {
		t.Fatalf("delayed material should wait, not become infeasible; score=%#v", score.Feasibility)
	}
	if score.Material.AggregateReplenishmentCount != 0 {
		t.Fatalf("delayed material should not recommend replenishment when real future arrival exists; materials=%v", score.Material.AggregateMaterialIDs)
	}
	p := proposalByJob(result.Proposals, jobID)
	if p == nil {
		t.Fatalf("missing proposal for delayed material job %s", jobID)
	}
	start := earliestSlotStart(p)
	if start.IsZero() {
		t.Fatalf("delayed material job has no slot: %#v", p)
	}
	if start.Before(arrivalAt) {
		t.Fatalf("delayed material job starts at %s before material arrival %s", start.Format(time.RFC3339), arrivalAt.Format(time.RFC3339))
	}
}

func TestHTTPRunnerTrueShortageBlocksOnlyAffectedJobs(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "60000")

	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	blockedID, unaffectedID := seedTrueShortageAndUnaffectedFixture(t, r)

	runner := schedulereval.HTTPRunner{Handler: r, OrderBy: "epo", Headers: plannerHeaders()}
	result, err := runner.Run(t.Context(), schedulereval.RunRequest{
		ScenarioID:              schedulereval.ScenarioTrueMaterialShortage,
		Endpoint:                schedulereval.EndpointBatchProposals,
		IncludeInventoryActions: true,
		DryRun:                  true,
	})
	if err != nil {
		t.Fatalf("run true shortage scenario: %v", err)
	}
	score := schedulereval.Evaluate(result, schedulereval.EvaluateOptions{})
	if len(score.Failures) > 0 {
		t.Fatalf("true shortage scorecard hard failures: %#v", score.Failures)
	}
	if score.Feasibility.InfeasibleJobs != 1 {
		t.Fatalf("infeasible jobs=%d, want exactly affected job", score.Feasibility.InfeasibleJobs)
	}
	if !containsString(score.Feasibility.BlockedJobIDs, blockedID) {
		t.Fatalf("blocked jobs=%v, want %s", score.Feasibility.BlockedJobIDs, blockedID)
	}
	if score.Material.AggregateReplenishmentCount == 0 || !containsString(score.Material.AggregateMaterialIDs, "MAT-EVAL-NONE") {
		t.Fatalf("expected MAT-EVAL-NONE aggregate row; material score=%#v", score.Material)
	}
	if p := proposalByJob(result.Proposals, unaffectedID); p == nil || !p.Feasible || len(p.ProposedSlots) == 0 {
		t.Fatalf("unaffected job should remain feasible with slots; proposal=%#v", p)
	}
}

func TestHTTPRunnerResourceOverloadDoesNotCreateMaterialShortage(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "60000")

	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	seedResourceOverloadFixture(t, r)

	runner := schedulereval.HTTPRunner{Handler: r, OrderBy: "edd", Headers: plannerHeaders()}
	score, err := runner.RunScorecard(t.Context(), schedulereval.RunRequest{
		ScenarioID: schedulereval.ScenarioResourceOverload,
		Endpoint:   schedulereval.EndpointBatchProposals,
		DryRun:     true,
	}, schedulereval.EvaluateOptions{})
	if err != nil {
		t.Fatalf("run resource overload scorecard: %v", err)
	}
	if len(score.Failures) > 0 {
		t.Fatalf("resource overload scorecard hard failures: %#v", score.Failures)
	}
	if score.Material.AggregateReplenishmentCount != 0 || score.Material.MaterialShortageProposalCount != 0 {
		t.Fatalf("resource overload should not be reported as material shortage; material score=%#v", score.Material)
	}
	if score.Feasibility.FeasibleJobs == 0 {
		t.Fatalf("resource overload should still generate feasible-or-late schedules; score=%#v", score.Feasibility)
	}
}

func TestHTTPRunnerChildBOMShortageTracesToRawMaterial(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "90000")

	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)
	parentJobID := seedChildBOMShortageFixture(t, r)

	runner := schedulereval.HTTPRunner{Handler: r, OrderBy: "epo", Headers: plannerHeaders()}
	result, err := runner.Run(t.Context(), schedulereval.RunRequest{
		ScenarioID:              schedulereval.ScenarioChildBOMShortage,
		Endpoint:                schedulereval.EndpointBatchProposals,
		IncludeInventoryActions: true,
		DryRun:                  true,
	})
	if err != nil {
		t.Fatalf("run child BOM shortage scenario: %v", err)
	}
	score := schedulereval.Evaluate(result, schedulereval.EvaluateOptions{})
	if len(score.Failures) > 0 {
		t.Fatalf("child BOM scorecard hard failures: %#v", score.Failures)
	}
	if score.Material.AggregateReplenishmentCount == 0 || !containsString(score.Material.AggregateMaterialIDs, "MAT-EVAL-CHILD-RAW") {
		t.Fatalf("child BOM shortage should recommend raw material MAT-EVAL-CHILD-RAW; material score=%#v", score.Material)
	}
	p := proposalByJob(result.Proposals, parentJobID)
	if p == nil {
		t.Fatalf("missing parent proposal %s", parentJobID)
	}
	if !proposalHasRawChildEvidence(p, "MAT-EVAL-CHILD-RAW") {
		t.Fatalf("parent shortage should trace to raw child material; proposal=%#v", p)
	}
}

func seedNoShortageControl(t *testing.T, r *gin.Engine) {
	t.Helper()
	mustPostOK(t, r, "/api/v1/products", map[string]interface{}{
		"product_id": "P-EVAL-OK", "product_name": "Eval No Shortage Product",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-EVAL-OK", "product_id": "P-EVAL-OK", "process_name": "Eval No Shortage Process",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes/PRC-EVAL-OK/steps", map[string]interface{}{
		"step_id":                 "STEP-EVAL-OK",
		"step_sequence":           1,
		"step_name":               "Eval machine step",
		"machine_type_required":   "EVAL_OK",
		"default_processing_time": 30,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-EVAL-OK", "machine_name": "Eval OK Machine", "machine_type": "EVAL_OK", "capacity_per_hour": 60,
	}, http.StatusCreated)
	for i := 0; i < 2; i++ {
		createEvalJob(t, r, "P-EVAL-OK", "medium", time.Now().UTC().Add(time.Duration(24+i)*time.Hour), fmt.Sprintf("eval no shortage %d", i))
	}
}

func seedDelayedAndStarvedMaterialFixture(t *testing.T, r *gin.Engine) {
	t.Helper()
	mustPostOK(t, r, "/api/v1/products", map[string]interface{}{
		"product_id": "P-EVAL-MAT", "product_name": "Eval Material Product",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-EVAL-MAT", "product_id": "P-EVAL-MAT", "process_name": "Eval Material Process",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes/PRC-EVAL-MAT/steps", map[string]interface{}{
		"step_id":                 "STEP-EVAL-MAT",
		"step_sequence":           1,
		"step_name":               "Eval material constrained step",
		"machine_type_required":   "EVAL_MAT",
		"default_processing_time": 30,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-EVAL-MAT", "machine_name": "Eval Material Machine", "machine_type": "EVAL_MAT", "capacity_per_hour": 60,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-LIMIT", "material_name": "Eval Limited Material", "current_stock": 10, "unit": "kg",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/process-steps/STEP-EVAL-MAT/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-LIMIT", "role": "input", "quantity_per_unit": 10, "unit": "kg",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/inventory/expected-arrivals", map[string]interface{}{
		"material_id": "MAT-EVAL-LIMIT", "quantity": 10, "expected_arrive_at": time.Now().UTC().Add(4 * time.Hour).Truncate(time.Second).Format(time.RFC3339),
	}, http.StatusCreated)
	createEvalJob(t, r, "P-EVAL-MAT", "high", time.Now().UTC().Add(48*time.Hour), "eval current material")
	createEvalJob(t, r, "P-EVAL-MAT", "medium", time.Now().UTC().Add(49*time.Hour), "eval wait material")
	createEvalJob(t, r, "P-EVAL-MAT", "low", time.Now().UTC().Add(50*time.Hour), "eval starved material")
}

func seedDelayedMaterialOnlyFixture(t *testing.T, r *gin.Engine) (time.Time, string) {
	t.Helper()
	mustPostOK(t, r, "/api/v1/products", map[string]interface{}{
		"product_id": "P-EVAL-WAIT", "product_name": "Eval Wait Material Product",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-EVAL-WAIT", "product_id": "P-EVAL-WAIT", "process_name": "Eval Wait Process",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes/PRC-EVAL-WAIT/steps", map[string]interface{}{
		"step_id":                 "STEP-EVAL-WAIT",
		"step_sequence":           1,
		"step_name":               "Eval wait material step",
		"machine_type_required":   "EVAL_WAIT",
		"default_processing_time": 30,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-EVAL-WAIT", "machine_name": "Eval Wait Machine", "machine_type": "EVAL_WAIT", "capacity_per_hour": 60,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-WAIT", "material_name": "Eval Future Material", "current_stock": 0, "unit": "kg",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/process-steps/STEP-EVAL-WAIT/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-WAIT", "role": "input", "quantity_per_unit": 10, "unit": "kg",
	}, http.StatusCreated)
	arrivalAt := time.Now().UTC().Add(4 * time.Hour).Truncate(time.Second)
	mustPostOK(t, r, "/api/v1/inventory/expected-arrivals", map[string]interface{}{
		"material_id": "MAT-EVAL-WAIT", "quantity": 10, "expected_arrive_at": arrivalAt.Format(time.RFC3339),
	}, http.StatusCreated)
	jobID := createEvalJob(t, r, "P-EVAL-WAIT", "medium", time.Now().UTC().Add(48*time.Hour), "eval future material should wait")
	return arrivalAt, jobID
}

func seedTrueShortageAndUnaffectedFixture(t *testing.T, r *gin.Engine) (string, string) {
	t.Helper()
	mustPostOK(t, r, "/api/v1/products", map[string]interface{}{
		"product_id": "P-EVAL-BLOCKED", "product_name": "Eval Blocked Material Product",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-EVAL-BLOCKED", "product_id": "P-EVAL-BLOCKED", "process_name": "Eval Blocked Process",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes/PRC-EVAL-BLOCKED/steps", map[string]interface{}{
		"step_id":                 "STEP-EVAL-BLOCKED",
		"step_sequence":           1,
		"step_name":               "Eval blocked material step",
		"machine_type_required":   "EVAL_BLOCKED",
		"default_processing_time": 30,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-EVAL-BLOCKED", "machine_name": "Eval Blocked Machine", "machine_type": "EVAL_BLOCKED", "capacity_per_hour": 60,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-NONE", "material_name": "Eval Missing Material", "current_stock": 0, "unit": "kg",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/process-steps/STEP-EVAL-BLOCKED/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-NONE", "role": "input", "quantity_per_unit": 10, "unit": "kg",
	}, http.StatusCreated)

	mustPostOK(t, r, "/api/v1/products", map[string]interface{}{
		"product_id": "P-EVAL-FREE", "product_name": "Eval Unaffected Product",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-EVAL-FREE", "product_id": "P-EVAL-FREE", "process_name": "Eval Unaffected Process",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes/PRC-EVAL-FREE/steps", map[string]interface{}{
		"step_id":                 "STEP-EVAL-FREE",
		"step_sequence":           1,
		"step_name":               "Eval unaffected step",
		"machine_type_required":   "EVAL_FREE",
		"default_processing_time": 30,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-EVAL-FREE", "machine_name": "Eval Free Machine", "machine_type": "EVAL_FREE", "capacity_per_hour": 60,
	}, http.StatusCreated)

	deadline := time.Now().UTC().Add(48 * time.Hour)
	blockedID := createEvalJob(t, r, "P-EVAL-BLOCKED", "high", deadline, "eval true material shortage")
	unaffectedID := createEvalJob(t, r, "P-EVAL-FREE", "medium", deadline, "eval unaffected by shortage")
	return blockedID, unaffectedID
}

func seedResourceOverloadFixture(t *testing.T, r *gin.Engine) {
	t.Helper()
	mustPostOK(t, r, "/api/v1/products", map[string]interface{}{
		"product_id": "P-EVAL-LOAD", "product_name": "Eval Resource Load Product",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-EVAL-LOAD", "product_id": "P-EVAL-LOAD", "process_name": "Eval Resource Load Process",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes/PRC-EVAL-LOAD/steps", map[string]interface{}{
		"step_id":                 "STEP-EVAL-LOAD",
		"step_sequence":           1,
		"step_name":               "Eval overloaded machine step",
		"machine_type_required":   "EVAL_LOAD",
		"default_processing_time": 180,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-EVAL-LOAD", "machine_name": "Eval Single Load Machine", "machine_type": "EVAL_LOAD", "capacity_per_hour": 10,
	}, http.StatusCreated)
	for i := 0; i < 5; i++ {
		createEvalJob(t, r, "P-EVAL-LOAD", "medium", time.Now().UTC().Add(time.Duration(2+i)*time.Hour), fmt.Sprintf("eval resource overload %d", i))
	}
}

func seedChildBOMShortageFixture(t *testing.T, r *gin.Engine) string {
	t.Helper()
	mustPostOK(t, r, "/api/v1/products", map[string]interface{}{
		"product_id": "P-EVAL-CHILD", "product_name": "Eval Child Product",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-EVAL-CHILD", "product_id": "P-EVAL-CHILD", "process_name": "Eval Child Process",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes/PRC-EVAL-CHILD/steps", map[string]interface{}{
		"step_id":                 "STEP-EVAL-CHILD",
		"step_sequence":           1,
		"step_name":               "Eval child raw step",
		"machine_type_required":   "EVAL_CHILD",
		"default_processing_time": 30,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-EVAL-CHILD", "machine_name": "Eval Child Machine", "machine_type": "EVAL_CHILD", "capacity_per_hour": 60,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-CHILD-RAW", "material_name": "Eval Missing Child Raw", "current_stock": 0, "unit": "kg",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/process-steps/STEP-EVAL-CHILD/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-CHILD-RAW", "role": "input", "quantity_per_unit": 10, "unit": "kg",
	}, http.StatusCreated)

	mustPostOK(t, r, "/api/v1/products", map[string]interface{}{
		"product_id": "P-EVAL-PARENT", "product_name": "Eval Parent Product",
	}, http.StatusCreated)
	mustRequestOK(t, r, http.MethodPut, "/api/v1/products/P-EVAL-PARENT/bom", map[string]interface{}{
		"bom_items": []map[string]interface{}{
			{"product_id": "P-EVAL-CHILD", "quantity_per_unit": 1, "unit": "pcs"},
		},
	}, http.StatusOK)
	mustPostOK(t, r, "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-EVAL-PARENT", "product_id": "P-EVAL-PARENT", "process_name": "Eval Parent Process",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes/PRC-EVAL-PARENT/steps", map[string]interface{}{
		"step_id":                 "STEP-EVAL-PARENT",
		"step_sequence":           1,
		"step_name":               "Eval parent assembly step",
		"machine_type_required":   "EVAL_PARENT",
		"default_processing_time": 30,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/process-steps/STEP-EVAL-PARENT/materials", map[string]interface{}{
		"product_id": "P-EVAL-CHILD", "role": "input", "quantity_per_unit": 1, "unit": "pcs",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-EVAL-PARENT", "machine_name": "Eval Parent Machine", "machine_type": "EVAL_PARENT", "capacity_per_hour": 60,
	}, http.StatusCreated)
	return createEvalJob(t, r, "P-EVAL-PARENT", "high", time.Now().UTC().Add(48*time.Hour), "eval child bom raw shortage")
}

func createEvalJob(t *testing.T, r *gin.Engine, productID, priority string, deadline time.Time, notes string) string {
	t.Helper()
	w := testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/jobs", map[string]interface{}{
		"product_id":      productID,
		"quantity_total":  1,
		"deadline":        deadline.Format(time.RFC3339),
		"priority":        priority,
		"notes":           notes,
		"allow_auto_plan": true,
	}, plannerHeaders())
	if w.Code != http.StatusCreated {
		t.Fatalf("create eval job status=%d, body=%s", w.Code, w.Body.String())
	}
	success, data, errMsg := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("create eval job success=false error=%q body=%s", errMsg, w.Body.String())
	}
	return data.(map[string]interface{})["job_id"].(string)
}

func mustPostOK(t *testing.T, r *gin.Engine, path string, body interface{}, status int) {
	t.Helper()
	mustRequestOK(t, r, http.MethodPost, path, body, status)
}

func mustRequestOK(t *testing.T, r *gin.Engine, method string, path string, body interface{}, status int) {
	t.Helper()
	w := testutil.RequestWithHeaders(r, method, path, body, plannerHeaders())
	if w.Code != status {
		t.Fatalf("%s %s status=%d, want %d, body=%s", method, path, w.Code, status, w.Body.String())
	}
	success, _, errMsg := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("%s %s success=false error=%q body=%s", method, path, errMsg, w.Body.String())
	}
}

func plannerHeaders() map[string]string {
	return map[string]string{
		"X-User-Id":   "scheduler-eval-test",
		"X-User-Role": "planner",
	}
}

func proposalByJob(proposals []*service.SchedulingProposal, jobID string) *service.SchedulingProposal {
	for _, p := range proposals {
		if p != nil && p.JobID == jobID {
			return p
		}
	}
	return nil
}

func earliestSlotStart(p *service.SchedulingProposal) time.Time {
	var out time.Time
	if p == nil {
		return out
	}
	for _, slot := range p.ProposedSlots {
		if slot.ScheduledStart.IsZero() {
			continue
		}
		if out.IsZero() || slot.ScheduledStart.Before(out) {
			out = slot.ScheduledStart
		}
	}
	return out
}

func containsString(values []string, want string) bool {
	for _, value := range values {
		if value == want {
			return true
		}
	}
	return false
}

func proposalHasRawChildEvidence(p *service.SchedulingProposal, materialID string) bool {
	if p == nil {
		return false
	}
	for _, sh := range p.MaterialShortages {
		for _, opt := range sh.PerMaterialResolutions {
			if opt.MaterialID == materialID {
				return true
			}
			if opt.Replenishment != nil && opt.Replenishment.MaterialID == materialID {
				return true
			}
		}
	}
	for _, opt := range p.ShortageResolutions {
		if opt.MaterialID == materialID {
			return true
		}
		if opt.Replenishment != nil && opt.Replenishment.MaterialID == materialID {
			return true
		}
	}
	for _, dep := range p.DependentJobs {
		if dep.ReplenishmentSuggestion != nil && dep.ReplenishmentSuggestion.MaterialID == materialID {
			return true
		}
		for _, opt := range dep.ResolutionOptions {
			if opt.MaterialID == materialID {
				return true
			}
			if opt.Replenishment != nil && opt.Replenishment.MaterialID == materialID {
				return true
			}
		}
	}
	return false
}
