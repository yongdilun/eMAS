package handler_test

import (
	"emas/internal/domain"
	"emas/internal/repository"
	"emas/internal/seeddata"
	"encoding/json"
	"net/http"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"emas/internal/router"
	"emas/internal/testutil"

	"github.com/gin-gonic/gin"
	_ "github.com/ncruces/go-sqlite3/embed"
	"github.com/ncruces/go-sqlite3/gormlite"
	"gorm.io/gorm"
)

func TestBatchProposalsPrioritizesMaterialAndWaitsForRealArrivals(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "180000")

	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	mustPostOK(t, r, "/api/v1/products", map[string]interface{}{
		"product_id": "P-MAT-PLAN", "product_name": "Material Planned Product",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-MAT-PLAN", "product_id": "P-MAT-PLAN", "process_name": "Material Planning Process",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes/PRC-MAT-PLAN/steps", map[string]interface{}{
		"step_id":                 "STEP-MAT-PLAN",
		"step_sequence":           1,
		"step_name":               "Material constrained step",
		"machine_type_required":   "MATPLAN",
		"default_processing_time": 30,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-MAT-PLAN", "machine_name": "Material Planning Machine", "machine_type": "MATPLAN", "capacity_per_hour": 60,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-PLAN-LIMIT", "material_name": "Limited Material", "current_stock": 10, "unit": "kg",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/process-steps/STEP-MAT-PLAN/materials", map[string]interface{}{
		"material_id": "MAT-PLAN-LIMIT", "role": "input", "quantity_per_unit": 10, "unit": "kg",
	}, http.StatusCreated)

	arrivalAt := time.Now().UTC().Add(4 * time.Hour).Truncate(time.Second)
	mustPostOK(t, r, "/api/v1/inventory/expected-arrivals", map[string]interface{}{
		"material_id": "MAT-PLAN-LIMIT", "quantity": 10, "expected_arrive_at": arrivalAt.Format(time.RFC3339),
	}, http.StatusCreated)

	deadline := time.Now().UTC().Add(48 * time.Hour).Format(time.RFC3339)
	highID := createMaterialPlanningJob(t, r, "high", deadline)
	waitID := createMaterialPlanningJob(t, r, "medium", time.Now().UTC().Add(49*time.Hour).Format(time.RFC3339))
	starvedID := createMaterialPlanningJob(t, r, "low", time.Now().UTC().Add(50*time.Hour).Format(time.RFC3339))

	w := testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"job_ids":  []string{starvedID, waitID, highID},
		"order_by": "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("batch-proposals status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("batch-proposals success=false body=%s", w.Body.String())
	}

	payload := data.(map[string]interface{})
	proposals := proposalsByJob(payload["proposals"].([]interface{}))
	high := proposals[highID]
	waiting := proposals[waitID]
	starved := proposals[starvedID]
	if high == nil || waiting == nil || starved == nil {
		t.Fatalf("expected proposals for all jobs, got %#v", proposals)
	}
	if !proposalFeasible(high) {
		t.Fatalf("high-priority job should consume current stock and remain feasible: %#v", high)
	}
	if !proposalFeasible(waiting) {
		t.Fatalf("medium-priority job should wait for the real expected arrival and remain feasible: %#v", waiting)
	}
	waitStart := earliestProposalStart(t, waiting)
	if waitStart.Before(arrivalAt) {
		t.Fatalf("waiting job starts at %s before real material arrival %s", waitStart.Format(time.RFC3339), arrivalAt.Format(time.RFC3339))
	}
	if proposalFeasible(starved) {
		t.Fatalf("starved low-priority job should be infeasible because no real material exists later in the timeline: %#v", starved)
	}
	if !blockedReasonsContainShortage(starved["blocked_reasons"]) {
		t.Fatalf("starved job should carry material shortage reason, got %#v", starved["blocked_reasons"])
	}
	if !proposalHasDirectShortageEvidence(starved) {
		t.Fatalf("starved job should expose shortage detail for resolution center: %#v", starved)
	}
	summary := payload["summary"].(map[string]interface{})
	if blocked, _ := summary["blocked"].(float64); int(blocked) != 1 {
		t.Fatalf("summary.blocked=%v, want only the starved job blocked", summary["blocked"])
	}

	suggestions := materialSuggestionsFromSummary(t, summary)
	if len(suggestions) == 0 {
		t.Fatalf("expected material_replenishment_aggregate suggestions, summary=%#v", summary)
	}
	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/apply-replenishment-batch", map[string]interface{}{
		"suggestions": suggestions,
		"order_by":    "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("apply material aggregate status = %d, body=%s", w.Code, w.Body.String())
	}

	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/reschedule-all", map[string]interface{}{
		"order_by": "epo",
		"dry_run":  true,
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("reschedule-all after material apply status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("reschedule-all success=false body=%s", w.Body.String())
	}
	replanPayload := data.(map[string]interface{})
	replanSummary := replanPayload["summary"].(map[string]interface{})
	assertNoScheduleProductionAggregate(t, replanSummary)
	if blocked, _ := replanSummary["blocked"].(float64); int(blocked) != 0 {
		t.Fatalf("after applying recommended material, summary.blocked=%v, want 0; summary=%#v", replanSummary["blocked"], replanSummary)
	}
	replanned := proposalsByJob(replanPayload["proposals"].([]interface{}))
	for _, jobID := range []string{highID, waitID, starvedID} {
		p := replanned[jobID]
		if p == nil {
			t.Fatalf("after material apply, job %s missing from reschedule proposals", jobID)
		}
		if !proposalFeasible(p) {
			t.Fatalf("after material apply, job %s should be feasible: %#v", jobID, p)
		}
		if slotCount(p) == 0 {
			t.Fatalf("after material apply, job %s should have proposed slots: %#v", jobID, p)
		}
	}
}

func TestSeededMaterialApplyClearsShortageAndKeepsMaterialActionsAtSlotTime(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "180000")

	db := testutil.NewTestDB(t)
	testutil.SeedCanonical(t, db)
	if err := db.Model(&domain.InventoryMaterials{}).
		Where("material_id IN ?", []string{"MAT-011", "MAT-014"}).
		Updates(map[string]interface{}{
			"current_stock": 0,
			"status":        domain.InventoryStatusOutOfStock,
		}).Error; err != nil {
		t.Fatalf("create deterministic subproduct raw-material shortage: %v", err)
	}
	if err := db.Model(&domain.ProductInventory{}).
		Where("product_id IN ?", []string{"P-007", "P-009"}).
		Updates(map[string]interface{}{
			"quantity_on_hand":  0,
			"quantity_reserved": 0,
		}).Error; err != nil {
		t.Fatalf("create deterministic subproduct stock shortage: %v", err)
	}
	for _, materialID := range []string{"MAT-011", "MAT-014"} {
		var mat domain.InventoryMaterials
		if err := db.First(&mat, "material_id = ?", materialID).Error; err != nil {
			t.Fatalf("load fixture material %s: %v", materialID, err)
		}
		if mat.CurrentStock != 0 {
			t.Fatalf("fixture material %s current_stock=%v, want 0", materialID, mat.CurrentStock)
		}
	}
	r := testutil.NewTestRouter(db, router.Setup)

	targetIDs := []string{"JOB-SEED-019", "JOB-SEED-021", "JOB-SEED-026"}
	if err := db.Model(&domain.Job{}).
		Where("job_id NOT IN ?", targetIDs).
		Where("status IN ?", []string{
			domain.JobStatusPlanned,
			domain.JobStatusScheduled,
			domain.JobStatusBlocked,
			domain.JobStatusPaused,
			domain.JobStatusRunning,
		}).
		Update("status", domain.JobStatusCompleted).Error; err != nil {
		t.Fatalf("complete non-target seed jobs: %v", err)
	}
	fixtureID := createSeededDirectMaterialShortageFixture(t, r)
	jobIDs := append(targetIDs, fixtureID)

	w := testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"job_ids":                   jobIDs,
		"order_by":                  "epo",
		"include_inventory_actions": true,
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("batch-proposals status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("batch-proposals success=false body=%s", w.Body.String())
	}
	payload := data.(map[string]interface{})
	summary := payload["summary"].(map[string]interface{})
	assertNoScheduleProductionAggregate(t, summary)

	suggestions := materialSuggestionsFromSummary(t, summary)
	if len(suggestions) == 0 {
		t.Fatalf("expected material recommendations, summary=%s", prettyValueJSON(summary))
	}
	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/apply-replenishment-batch", map[string]interface{}{
		"suggestions": suggestions,
		"order_by":    "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("apply material aggregate status = %d, body=%s", w.Code, w.Body.String())
	}

	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"job_ids":                   jobIDs,
		"order_by":                  "epo",
		"include_inventory_actions": true,
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("post-apply batch-proposals status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("post-apply batch-proposals success=false body=%s", w.Body.String())
	}
	replannedPayload := data.(map[string]interface{})
	replannedSummary := replannedPayload["summary"].(map[string]interface{})
	assertNoScheduleProductionAggregate(t, replannedSummary)
	replanned := proposalsByJob(replannedPayload["proposals"].([]interface{}))
	for _, jobID := range jobIDs {
		p := replanned[jobID]
		if p == nil {
			t.Fatalf("post-apply proposal for %s missing", jobID)
		}
		assertMaterialActionsAtOrAfterSlots(t, p)
		if !proposalFeasible(p) {
			t.Fatalf("post-apply proposal %s should be feasible; proposal=%s summary=%s", jobID, prettyValueJSON(p), prettyValueJSON(replannedSummary))
		}
	}
	if blocked, _ := replannedSummary["blocked"].(float64); int(blocked) != 0 {
		t.Fatalf("post-apply summary.blocked=%v, want 0; summary=%s", replannedSummary["blocked"], prettyValueJSON(replannedSummary))
	}
}

func TestSeededSubproductRawMaterialApplyClearsRepeatedChildAggregate(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "180000")

	db := testutil.NewTestDB(t)
	testutil.SeedCanonical(t, db)
	if err := db.Model(&domain.InventoryMaterials{}).
		Where("material_id IN ?", []string{"MAT-011", "MAT-014"}).
		Updates(map[string]interface{}{
			"current_stock": 0,
			"status":        domain.InventoryStatusOutOfStock,
		}).Error; err != nil {
		t.Fatalf("zero child raw material stock: %v", err)
	}
	if err := db.Where("material_id IN ?", []string{"MAT-011", "MAT-014"}).
		Delete(&domain.InventoryExpectedArrival{}).Error; err != nil {
		t.Fatalf("remove existing child raw material arrivals: %v", err)
	}
	if err := db.Model(&domain.ProductInventory{}).
		Where("product_id IN ?", []string{"P-007", "P-009"}).
		Updates(map[string]interface{}{
			"quantity_on_hand":  0,
			"quantity_reserved": 0,
		}).Error; err != nil {
		t.Fatalf("zero child product inventory: %v", err)
	}
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/reschedule-all", map[string]interface{}{
		"order_by": "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("initial reschedule-all status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("initial reschedule-all success=false body=%s", w.Body.String())
	}
	payload := data.(map[string]interface{})
	summary := payload["summary"].(map[string]interface{})
	assertNoScheduleProductionAggregate(t, summary)
	suggestions := materialSuggestionsFromSummary(t, summary)
	if !suggestionsContainMaterials(suggestions, "MAT-011", "MAT-014") {
		t.Fatalf("expected child raw-material recommendations for MAT-011 and MAT-014; summary=%s", prettyValueJSON(summary))
	}

	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/apply-replenishment-batch", map[string]interface{}{
		"suggestions": suggestions,
		"order_by":    "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("apply child raw material aggregate status = %d, body=%s", w.Code, w.Body.String())
	}
	success, applyData, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("apply child raw material aggregate success=false body=%s", w.Body.String())
	}
	created, _ := applyData.(map[string]interface{})["created_arrivals"].([]interface{})
	if len(created) == 0 {
		t.Fatalf("expected apply to create child raw-material arrivals, got %s", prettyValueJSON(applyData))
	}

	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/reschedule-all", map[string]interface{}{
		"order_by": "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("post-apply reschedule-all status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("post-apply reschedule-all success=false body=%s", w.Body.String())
	}
	replannedPayload := data.(map[string]interface{})
	replannedSummary := replannedPayload["summary"].(map[string]interface{})
	assertNoScheduleProductionAggregate(t, replannedSummary)
	assertNoMaterialShortageInfeasible(t, replannedPayload, "after applying child raw-material recommendations")
	remaining := materialSuggestionsFromSummary(t, replannedSummary)
	if suggestionsContainMaterials(remaining, "MAT-011", "MAT-014") {
		t.Fatalf("child raw-material rows repeated after apply; remaining=%s summary=%s", prettyValueJSON(remaining), prettyValueJSON(replannedSummary))
	}
	if blocked, _ := replannedSummary["blocked"].(float64); int(blocked) != 0 {
		t.Fatalf("post-apply summary.blocked=%v, want 0; summary=%s", replannedSummary["blocked"], prettyValueJSON(replannedSummary))
	}
}

func TestCanonicalSeedShortageResolutionOneShotClearsAllMaterialShortages(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "240000")

	db := testutil.NewTestDB(t)
	testutil.SeedCanonical(t, db)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"scope":    "all_unscheduled",
		"order_by": "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("initial canonical batch-proposals status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("initial canonical batch-proposals success=false body=%s", w.Body.String())
	}
	payload := data.(map[string]interface{})
	summary := payload["summary"].(map[string]interface{})
	assertNoScheduleProductionAggregate(t, summary)
	suggestions := materialSuggestionsFromSummary(t, summary)
	if len(suggestions) == 0 {
		t.Fatalf("canonical seed should expose unified material recommendations; summary=%s", prettyValueJSON(summary))
	}
	if !suggestionsContainMaterials(suggestions, "MAT-010") {
		t.Fatalf("canonical seed first aggregate must include child raw-material cascade MAT-010; suggestions=%s summary=%s", prettyValueJSON(suggestions), prettyValueJSON(summary))
	}

	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/apply-replenishment-batch", map[string]interface{}{
		"suggestions": suggestions,
		"order_by":    "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("canonical apply aggregate status = %d, body=%s", w.Code, w.Body.String())
	}
	success, applyData, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("canonical apply aggregate success=false body=%s", w.Body.String())
	}
	created, _ := applyData.(map[string]interface{})["created_arrivals"].([]interface{})
	if len(created) == 0 {
		t.Fatalf("expected canonical apply to create material arrivals, got %s", prettyValueJSON(applyData))
	}

	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/reschedule-all", map[string]interface{}{
		"order_by": "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("canonical post-apply reschedule-all status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("canonical post-apply reschedule-all success=false body=%s", w.Body.String())
	}
	replannedPayload := data.(map[string]interface{})
	replannedSummary := replannedPayload["summary"].(map[string]interface{})
	assertNoScheduleProductionAggregate(t, replannedSummary)
	assertNoMaterialShortageInfeasible(t, replannedPayload, "after canonical one-shot material apply")
	if remaining := materialSuggestionsFromSummary(t, replannedSummary); len(remaining) > 0 {
		t.Fatalf("canonical one-shot apply should leave no material aggregate rows; remaining=%s summary=%s", prettyValueJSON(remaining), prettyValueJSON(replannedSummary))
	}
	if fallback := proposalsWithMaterialRecommendations(replannedPayload); len(fallback) > 0 {
		t.Fatalf("canonical one-shot apply should not fall back to per-proposal shortage UI; proposals with recommendations=%s", strings.Join(fallback, ", "))
	}
	proposals, _ := replannedPayload["proposals"].([]interface{})
	if len(proposals) == 0 {
		t.Fatalf("canonical post-apply reschedule returned no proposals; payload=%s", prettyValueJSON(replannedPayload))
	}
	unscheduled := make([]string, 0)
	infeasible := make([]string, 0)
	for _, raw := range proposals {
		p, _ := raw.(map[string]interface{})
		if p == nil {
			continue
		}
		jobID, _ := p["job_id"].(string)
		if !proposalFeasible(p) {
			infeasible = append(infeasible, jobID)
			continue
		}
		if slotCount(p) == 0 {
			unscheduled = append(unscheduled, jobID)
		}
	}
	if len(infeasible) > 0 {
		t.Fatalf("canonical one-shot apply left infeasible proposals: %s", strings.Join(infeasible, ", "))
	}
	if len(unscheduled) > 0 {
		t.Fatalf("canonical one-shot apply left feasible proposals without slots: %s", strings.Join(unscheduled, ", "))
	}
	if blocked, _ := replannedSummary["blocked"].(float64); int(blocked) != 0 {
		t.Fatalf("canonical post-apply summary.blocked=%v, want 0; summary=%s", replannedSummary["blocked"], prettyValueJSON(replannedSummary))
	}
}

func TestCanonicalSeedRescheduleAllFirstAggregateIncludesDeepCascadeAndClears(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "240000")

	db := testutil.NewTestDB(t)
	testutil.SeedCanonical(t, db)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/reschedule-all", map[string]interface{}{
		"order_by": "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("initial canonical reschedule-all status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("initial canonical reschedule-all success=false body=%s", w.Body.String())
	}
	payload := data.(map[string]interface{})
	summary := payload["summary"].(map[string]interface{})
	assertNoScheduleProductionAggregate(t, summary)
	suggestions := materialSuggestionsFromSummary(t, summary)
	if len(suggestions) == 0 {
		t.Fatalf("canonical reschedule-all should expose unified material recommendations; summary=%s", prettyValueJSON(summary))
	}
	if !suggestionsContainMaterials(suggestions, "MAT-010") {
		t.Fatalf("canonical reschedule-all first aggregate must include deep child raw-material cascade MAT-010; suggestions=%s summary=%s", prettyValueJSON(suggestions), prettyValueJSON(summary))
	}
	if fallback := proposalsWithMaterialRecommendations(payload); len(fallback) > 0 {
		t.Fatalf("canonical reschedule-all first screen must use unified aggregate, not per-proposal fallback rows; proposals with recommendations=%s", strings.Join(fallback, ", "))
	}

	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/apply-replenishment-batch", map[string]interface{}{
		"suggestions": suggestions,
		"order_by":    "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("canonical reschedule-all aggregate apply status = %d, body=%s", w.Code, w.Body.String())
	}
	success, applyData, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("canonical reschedule-all aggregate apply success=false body=%s", w.Body.String())
	}
	created, _ := applyData.(map[string]interface{})["created_arrivals"].([]interface{})
	if len(created) == 0 {
		t.Fatalf("expected canonical reschedule-all aggregate apply to create material arrivals, got %s", prettyValueJSON(applyData))
	}

	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/reschedule-all", map[string]interface{}{
		"order_by": "epo",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("canonical post-apply reschedule-all status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("canonical post-apply reschedule-all success=false body=%s", w.Body.String())
	}
	replannedPayload := data.(map[string]interface{})
	replannedSummary := replannedPayload["summary"].(map[string]interface{})
	assertNoScheduleProductionAggregate(t, replannedSummary)
	assertNoMaterialShortageInfeasible(t, replannedPayload, "after canonical reschedule-all one-shot material apply")
	if remaining := materialSuggestionsFromSummary(t, replannedSummary); len(remaining) > 0 {
		t.Fatalf("canonical reschedule-all one-shot apply should leave no material aggregate rows; remaining=%s summary=%s", prettyValueJSON(remaining), prettyValueJSON(replannedSummary))
	}
	if fallback := proposalsWithMaterialRecommendations(replannedPayload); len(fallback) > 0 {
		t.Fatalf("canonical reschedule-all one-shot apply should not fall back to per-proposal shortage UI; proposals with recommendations=%s", strings.Join(fallback, ", "))
	}
	if blocked, _ := replannedSummary["blocked"].(float64); int(blocked) != 0 {
		t.Fatalf("canonical reschedule-all post-apply summary.blocked=%v, want 0; summary=%s", replannedSummary["blocked"], prettyValueJSON(replannedSummary))
	}
}

func TestCanonicalSeedFileBackedShortageResolutionMatchesSeededServer(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "240000")

	dbPath := t.TempDir() + "/canonical-seeded-server.sqlite"
	db, err := gorm.Open(gormlite.Open(dbPath), &gorm.Config{})
	if err != nil {
		t.Fatalf("open file-backed sqlite db: %v", err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		t.Fatalf("open file-backed sql db: %v", err)
	}
	t.Cleanup(func() { _ = sqlDB.Close() })
	sqlDB.SetMaxOpenConns(1)
	sqlDB.SetMaxIdleConns(1)

	if err := repository.AutoMigrate(db); err != nil {
		t.Fatalf("migrate file-backed db: %v", err)
	}
	testutil.SeedCanonical(t, db)
	if err := seeddata.ResetCanonicalDB(db, seeddata.SeedOptions{ValidateFingerprint: true}); err != nil {
		t.Fatalf("reset file-backed canonical db: %v", err)
	}
	r := testutil.NewTestRouter(db, router.Setup)

	type batchResult struct {
		index       int
		status      int
		body        string
		suggestions []map[string]interface{}
		summary     map[string]interface{}
	}
	results := make([]batchResult, 2)
	var wg sync.WaitGroup
	wg.Add(len(results))
	for i := range results {
		go func(idx int) {
			defer wg.Done()
			w := testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
				"scope":    "all_unscheduled",
				"order_by": "epo",
			}, plannerAuthHeaders())
			res := batchResult{index: idx, status: w.Code, body: w.Body.String()}
			if w.Code == http.StatusOK {
				success, data, _ := testutil.DecodeResponse(w)
				if success {
					payload := data.(map[string]interface{})
					res.summary = payload["summary"].(map[string]interface{})
					res.suggestions = materialSuggestionsFromSummary(t, res.summary)
				}
			}
			results[idx] = res
		}(i)
	}
	wg.Wait()
	for _, res := range results {
		if res.status != http.StatusOK {
			t.Fatalf("file-backed canonical batch-proposals[%d] status = %d, body=%s", res.index, res.status, res.body)
		}
		if len(res.suggestions) == 0 {
			t.Fatalf("file-backed canonical seed request[%d] should expose unified material recommendations; summary=%s", res.index, prettyValueJSON(res.summary))
		}
		if !suggestionsContainMaterials(res.suggestions, "MAT-010") {
			t.Fatalf("file-backed canonical seed request[%d] first aggregate must include MAT-010; suggestions=%s summary=%s", res.index, prettyValueJSON(res.suggestions), prettyValueJSON(res.summary))
		}
	}
}

func TestBatchProposalsDoesNotBlackBoxMarkAggregateOnlyJobsInfeasible(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "180000")

	db := testutil.NewTestDB(t)
	testutil.SeedCanonical(t, db)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"job_ids":  []string{"JOB-SEED-019", "JOB-SEED-021", "JOB-SEED-026"},
		"order_by": "edd",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("batch-proposals status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("batch-proposals success=false body=%s", w.Body.String())
	}

	payload := data.(map[string]interface{})
	summary := payload["summary"].(map[string]interface{})
	assertNoScheduleProductionAggregate(t, summary)
	affected := affectedJobsFromAggregate(summary, "material_replenishment_aggregate")
	proposals := payload["proposals"].([]interface{})
	if len(affected) == 0 {
		for _, raw := range proposals {
			p := raw.(map[string]interface{})
			if proposalFeasible(p) || !blockedReasonsContainShortage(p["blocked_reasons"]) {
				continue
			}
			if !proposalHasDirectShortageEvidence(p) {
				t.Fatalf("shortage-infeasible proposal without aggregate rows must expose direct shortage evidence: %#v", p)
			}
		}
		return
	}

	byJob := make(map[string]map[string]interface{}, len(proposals))
	for _, raw := range proposals {
		p := raw.(map[string]interface{})
		byJob[p["job_id"].(string)] = p
	}

	aggregateOnly := 0
	for jobID := range affected {
		p, ok := byJob[jobID]
		if !ok {
			t.Fatalf("aggregate affected job %s missing from proposals", jobID)
		}
		if proposalHasDirectShortageEvidence(p) {
			continue
		}
		aggregateOnly++
		if feasible, _ := p["feasible"].(bool); !feasible {
			t.Fatalf("aggregate-only affected job %s should not be individually infeasible without actionable shortage detail; proposal=%#v", jobID, p)
		}
		if blockedReasonsContainShortage(p["blocked_reasons"]) {
			t.Fatalf("aggregate-only affected job %s should not carry a black-box shortage reason: %#v", jobID, p["blocked_reasons"])
		}
	}

	if aggregateOnly == 0 {
		t.Logf("canonical seed material aggregate currently has no aggregate-only affected jobs")
	}
}

func TestBatchProposalsFullSeedKeepsAggregateShortagesOutOfPreviewFeasibility(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "180000")

	db := testutil.NewTestDB(t)
	testutil.SeedCanonical(t, db)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"scope":    "all_unscheduled",
		"order_by": "edd",
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("batch-proposals status = %d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("batch-proposals success=false body=%s", w.Body.String())
	}

	payload := data.(map[string]interface{})
	summary := payload["summary"].(map[string]interface{})
	assertNoScheduleProductionAggregate(t, summary)
	affected := affectedJobsFromAggregate(summary, "material_replenishment_aggregate")
	if len(affected) == 0 {
		t.Logf("full canonical seed has no material-replenishment aggregate; jobs can wait for future material without becoming shortage-infeasible")
	}

	proposals := payload["proposals"].([]interface{})
	shortageWithoutEvidence := make([]string, 0)
	infeasibleCount := 0
	directShortageCount := 0
	for _, raw := range proposals {
		p := raw.(map[string]interface{})
		feasible, _ := p["feasible"].(bool)
		if feasible {
			continue
		}
		infeasibleCount++
		if !blockedReasonsContainShortage(p["blocked_reasons"]) {
			continue
		}
		if proposalHasDirectShortageEvidence(p) {
			directShortageCount++
			continue
		}
		shortageWithoutEvidence = append(shortageWithoutEvidence, p["job_id"].(string))
	}

	if len(shortageWithoutEvidence) > 0 {
		t.Fatalf("shortage-infeasible proposals must expose direct shortage evidence, not only aggregate noise: %s", strings.Join(shortageWithoutEvidence, ", "))
	}
	if directShortageCount == 0 {
		t.Logf("full canonical seed has no shortage-infeasible proposal; waiting for future material is treated as feasible")
	}
	if blocked, _ := summary["blocked"].(float64); int(blocked) != infeasibleCount {
		t.Fatalf("summary.blocked=%v, feasible flags report %d infeasible proposals", summary["blocked"], infeasibleCount)
	}
}

func TestDirectSeededSubproductJobWithNoRawMaterialIsInfeasible(t *testing.T) {
	t.Setenv("AI_AUTH_REQUIRED", "true")
	t.Setenv("AI_BATCH_TIMEOUT_MS", "180000")

	db := testutil.NewTestDB(t)
	testutil.SeedCanonical(t, db)
	if err := db.Model(&domain.InventoryMaterials{}).
		Where("material_id IN ?", []string{"MAT-011", "MAT-014"}).
		Updates(map[string]interface{}{
			"current_stock": 0,
			"status":        domain.InventoryStatusOutOfStock,
		}).Error; err != nil {
		t.Fatalf("create raw-material shortage: %v", err)
	}
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, http.MethodPost, "/api/v1/jobs", map[string]interface{}{
		"product_id":      "P-007",
		"quantity_total":  100,
		"deadline":        time.Now().UTC().Add(7 * 24 * time.Hour).Format(time.RFC3339),
		"priority":        "high",
		"allow_auto_plan": true,
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create P-007 job status=%d body=%s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("create P-007 job success=false body=%s", w.Body.String())
	}
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.RequestWithHeaders(r, http.MethodPost, "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
		"job_ids": []string{jobID},
	}, plannerAuthHeaders())
	if w.Code != http.StatusOK {
		t.Fatalf("batch-proposals P-007 status=%d body=%s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("batch-proposals P-007 success=false body=%s", w.Body.String())
	}
	payload := data.(map[string]interface{})
	proposals := payload["proposals"].([]interface{})
	if len(proposals) != 1 {
		t.Fatalf("expected one proposal, got %d", len(proposals))
	}
	p := proposals[0].(map[string]interface{})
	if proposalFeasible(p) {
		t.Fatalf("P-007 job with no raw material should be infeasible; proposal=%s summary=%s", prettyValueJSON(p), prettyValueJSON(payload["summary"]))
	}
	if !proposalHasDirectShortageEvidence(p) {
		t.Fatalf("P-007 infeasible job should expose material shortage evidence; proposal=%s", prettyValueJSON(p))
	}
}

func affectedJobsFromAggregate(summary map[string]interface{}, key string) map[string]bool {
	out := make(map[string]bool)
	rows, _ := summary[key].([]interface{})
	for _, raw := range rows {
		row, _ := raw.(map[string]interface{})
		jobs, _ := row["affected_job_ids"].([]interface{})
		for _, job := range jobs {
			if id, ok := job.(string); ok && id != "" {
				out[id] = true
			}
		}
	}
	return out
}

func assertNoScheduleProductionAggregate(t *testing.T, summary map[string]interface{}) {
	t.Helper()
	if rows, ok := summary["schedule_production_aggregate"].([]interface{}); ok && len(rows) > 0 {
		t.Fatalf("schedule_production_aggregate should not be returned, got %#v", rows)
	}
}

func materialSuggestionsFromSummary(t *testing.T, summary map[string]interface{}) []map[string]interface{} {
	t.Helper()
	rows, _ := summary["material_replenishment_aggregate"].([]interface{})
	out := make([]map[string]interface{}, 0, len(rows))
	for _, raw := range rows {
		row, _ := raw.(map[string]interface{})
		materialID, _ := row["material_id"].(string)
		qty, _ := row["recommended_qty"].(float64)
		arriveAt, _ := row["suggested_arrive_at"].(string)
		if materialID == "" || qty <= 0 || arriveAt == "" {
			t.Fatalf("invalid material aggregate row: %#v", row)
		}
		out = append(out, map[string]interface{}{
			"material_id": materialID,
			"quantity":    qty,
			"arrive_at":   arriveAt,
		})
	}
	return out
}

func suggestionsContainMaterials(rows []map[string]interface{}, ids ...string) bool {
	wanted := make(map[string]bool, len(ids))
	for _, id := range ids {
		wanted[id] = false
	}
	for _, row := range rows {
		id, _ := row["material_id"].(string)
		if _, ok := wanted[id]; ok {
			wanted[id] = true
		}
	}
	for _, seen := range wanted {
		if !seen {
			return false
		}
	}
	return true
}

func blockedReasonsContainShortage(raw interface{}) bool {
	rows, _ := raw.([]interface{})
	for _, row := range rows {
		text, _ := row.(string)
		if strings.Contains(text, "shortage") {
			return true
		}
	}
	return false
}

func proposalHasDirectShortageEvidence(p map[string]interface{}) bool {
	if rows, ok := p["material_shortages"].([]interface{}); ok && len(rows) > 0 {
		return true
	}
	if rows, ok := p["shortage_resolutions"].([]interface{}); ok && len(rows) > 0 {
		return true
	}
	return false
}

func assertNoMaterialShortageInfeasible(t *testing.T, payload map[string]interface{}, context string) {
	t.Helper()
	summary, _ := payload["summary"].(map[string]interface{})
	proposals, _ := payload["proposals"].([]interface{})
	remaining := make([]string, 0)
	for _, raw := range proposals {
		p, _ := raw.(map[string]interface{})
		if p == nil || proposalFeasible(p) || !blockedReasonsContainShortage(p["blocked_reasons"]) {
			continue
		}
		remaining = append(remaining, p["job_id"].(string))
	}
	if len(remaining) > 0 {
		t.Fatalf("%s: material-shortage infeasible proposals remain: %s; summary=%s", context, strings.Join(remaining, ", "), prettyValueJSON(summary))
	}
}

func proposalsWithMaterialRecommendations(payload map[string]interface{}) []string {
	proposals, _ := payload["proposals"].([]interface{})
	out := make([]string, 0)
	for _, raw := range proposals {
		p, _ := raw.(map[string]interface{})
		if p == nil {
			continue
		}
		hasRecommendations := false
		if rows, ok := p["shortage_resolutions"].([]interface{}); ok && len(rows) > 0 {
			hasRecommendations = true
		}
		if rows, ok := p["material_shortages"].([]interface{}); ok {
			for _, row := range rows {
				shortage, _ := row.(map[string]interface{})
				if per, ok := shortage["per_material_resolutions"].([]interface{}); ok && len(per) > 0 {
					hasRecommendations = true
					break
				}
			}
		}
		if hasRecommendations {
			jobID, _ := p["job_id"].(string)
			out = append(out, jobID)
		}
	}
	sort.Strings(out)
	return out
}

func mustPostOK(t *testing.T, r *gin.Engine, path string, body map[string]interface{}, want int) {
	t.Helper()
	w := testutil.Request(r, http.MethodPost, path, body)
	if w.Code != want {
		t.Fatalf("POST %s status=%d, want %d, body=%s", path, w.Code, want, w.Body.String())
	}
}

func createMaterialPlanningJob(t *testing.T, r *gin.Engine, priority string, deadline string) string {
	t.Helper()
	w := testutil.Request(r, http.MethodPost, "/api/v1/jobs", map[string]interface{}{
		"product_id":      "P-MAT-PLAN",
		"quantity_total":  1,
		"deadline":        deadline,
		"priority":        priority,
		"allow_auto_plan": true,
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create %s priority job status=%d, body=%s", priority, w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("create %s priority job success=false body=%s", priority, w.Body.String())
	}
	return data.(map[string]interface{})["job_id"].(string)
}

func createSeededDirectMaterialShortageFixture(t *testing.T, r *gin.Engine) string {
	t.Helper()
	mustPostOK(t, r, "/api/v1/products", map[string]interface{}{
		"product_id": "P-E2E-MAT", "product_name": "E2E Material Shortage Product",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-E2E-MAT", "product_id": "P-E2E-MAT", "process_name": "E2E Material Shortage Process",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/processes/PRC-E2E-MAT/steps", map[string]interface{}{
		"step_id":                 "STEP-E2E-MAT",
		"step_sequence":           1,
		"step_name":               "E2E material constrained step",
		"machine_type_required":   "E2EMAT",
		"default_processing_time": 30,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-E2E-MAT", "machine_name": "E2E Material Machine", "machine_type": "E2EMAT", "capacity_per_hour": 60,
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-E2E-LIMIT", "material_name": "E2E Limited Material", "current_stock": 0, "unit": "kg",
	}, http.StatusCreated)
	mustPostOK(t, r, "/api/v1/process-steps/STEP-E2E-MAT/materials", map[string]interface{}{
		"material_id": "MAT-E2E-LIMIT", "role": "input", "quantity_per_unit": 5, "unit": "kg",
	}, http.StatusCreated)

	w := testutil.Request(r, http.MethodPost, "/api/v1/jobs", map[string]interface{}{
		"product_id":      "P-E2E-MAT",
		"quantity_total":  3,
		"deadline":        time.Now().UTC().Add(72 * time.Hour).Format(time.RFC3339),
		"priority":        "high",
		"allow_auto_plan": true,
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create seeded direct material fixture job status=%d, body=%s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatalf("create seeded direct material fixture job success=false body=%s", w.Body.String())
	}
	return data.(map[string]interface{})["job_id"].(string)
}

func proposalsByJob(rows []interface{}) map[string]map[string]interface{} {
	out := make(map[string]map[string]interface{}, len(rows))
	for _, raw := range rows {
		p, _ := raw.(map[string]interface{})
		if id, ok := p["job_id"].(string); ok && id != "" {
			out[id] = p
		}
	}
	return out
}

func proposalFeasible(p map[string]interface{}) bool {
	feasible, _ := p["feasible"].(bool)
	return feasible
}

func slotCount(p map[string]interface{}) int {
	rows, _ := p["proposed_slots"].([]interface{})
	return len(rows)
}

func earliestProposalStart(t *testing.T, p map[string]interface{}) time.Time {
	t.Helper()
	rows, _ := p["proposed_slots"].([]interface{})
	if len(rows) == 0 {
		t.Fatalf("proposal %v has no slots", p["job_id"])
	}
	var earliest time.Time
	for _, raw := range rows {
		row, _ := raw.(map[string]interface{})
		text, _ := row["scheduled_start"].(string)
		at, err := time.Parse(time.RFC3339Nano, text)
		if err != nil {
			t.Fatalf("parse scheduled_start %q: %v", text, err)
		}
		if earliest.IsZero() || at.Before(earliest) {
			earliest = at
		}
	}
	return earliest
}

func assertMaterialActionsAtOrAfterSlots(t *testing.T, p map[string]interface{}) {
	t.Helper()
	slotStartByStep := make(map[string]time.Time)
	for _, raw := range p["proposed_slots"].([]interface{}) {
		slot, _ := raw.(map[string]interface{})
		stepID, _ := slot["job_step_id"].(string)
		startText, _ := slot["scheduled_start"].(string)
		start, err := time.Parse(time.RFC3339Nano, startText)
		if err != nil {
			t.Fatalf("parse slot scheduled_start %q: %v", startText, err)
		}
		if existing, ok := slotStartByStep[stepID]; !ok || start.Before(existing) {
			slotStartByStep[stepID] = start
		}
	}
	for _, raw := range p["inventory_actions"].([]interface{}) {
		action, _ := raw.(map[string]interface{})
		if action["action_type"] != "reserve_material" {
			continue
		}
		stepID, _ := action["job_step_id"].(string)
		slotStart, ok := slotStartByStep[stepID]
		if !ok {
			continue
		}
		effectiveText, _ := action["effective_at"].(string)
		effective, err := time.Parse(time.RFC3339Nano, effectiveText)
		if err != nil {
			t.Fatalf("parse material action effective_at %q: %v", effectiveText, err)
		}
		if effective.Before(slotStart) {
			t.Fatalf("material action before returned slot for job %v step %s: action=%s slot=%s proposal=%s", p["job_id"], stepID, effective.Format(time.RFC3339), slotStart.Format(time.RFC3339), prettyValueJSON(p))
		}
	}
}

func prettyValueJSON(v interface{}) string {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return "<json error: " + err.Error() + ">"
	}
	return string(b)
}
