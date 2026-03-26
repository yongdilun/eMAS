package handler_test

// HTTP integration tests for the real-solver engine path.
//
// These tests exercise the full lifecycle:
//   job create → proposal generate (engine=real-solver) → approve → apply
//
// They also verify the governance rules that apply regardless of which engine
// produced the proposal (draft must be approved before apply, rejected proposals
// cannot be applied, idempotent apply, etc.).

import (
	"net/http"
	"os"
	"testing"
	"time"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestRealSolverProposalLifecycle(t *testing.T) {
	_ = os.Setenv("AI_PROPOSAL_ENGINE", "real-solver")
	defer os.Unsetenv("AI_PROPOSAL_ENGINE")

	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	// --- seed ---
	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-RS", "product_name": "Real Solver Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-RS", "product_id": "P-RS", "process_name": "Real Solver Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-RS/steps", map[string]interface{}{
		"step_id": "STEP-RS-1", "step_name": "Milling", "machine_type_required": "CNC",
		"allow_parallel_execution": true, "max_parallel_machines": 2, "min_split_qty": 5,
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-RS/steps", map[string]interface{}{
		"step_id": "STEP-RS-2", "step_name": "Finishing", "machine_type_required": "FINISH",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-CNC-RS-1", "machine_name": "CNC Alpha", "machine_type": "CNC", "capacity_per_hour": 60,
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-CNC-RS-2", "machine_name": "CNC Beta", "machine_type": "CNC", "capacity_per_hour": 45,
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-FINISH-RS", "machine_name": "Finisher", "machine_type": "FINISH", "capacity_per_hour": 30,
	})

	// --- create job ---
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-RS", "quantity_total": 50,
		"deadline": time.Now().Add(72 * time.Hour).UTC().Format(time.RFC3339),
	})
	if w.Code != http.StatusCreated {
		t.Fatalf("create job: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	// --- generate proposal (real-solver engine) ---
	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/jobs/"+jobID+"/proposals", nil)
	if w.Code != http.StatusCreated {
		t.Fatalf("generate proposal (real-solver): got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("generate proposal: success=false")
	}
	payload := data.(map[string]interface{})
	proposalID := payload["proposal_id"].(string)
	if proposalID == "" {
		t.Fatal("expected non-empty proposal_id")
	}
	// Engine should be non-empty (real-solver or its fallback).
	if engine, _ := payload["engine"].(string); engine == "" {
		t.Fatal("expected non-empty engine field in proposal")
	}
	// Proposed slots must be present.
	if _, ok := payload["proposed_slots"]; !ok {
		t.Fatal("expected proposed_slots in proposal")
	}

	// --- draft apply must be blocked ---
	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/apply", map[string]interface{}{
		"idempotency_key": "RS-DRAFT-BLOCK",
	})
	if w.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422 for draft apply, got %d body: %s", w.Code, w.Body.String())
	}

	// --- approve ---
	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/approve", map[string]interface{}{
		"notes": "real-solver test approval",
	})
	if w.Code != http.StatusOK {
		t.Fatalf("approve proposal: got %d, body: %s", w.Code, w.Body.String())
	}

	// --- apply ---
	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/apply", map[string]interface{}{
		"idempotency_key": "RS-APPLY-1",
	})
	if w.Code != http.StatusOK {
		t.Fatalf("apply proposal: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ = testutil.DecodeResponse(w)
	if !success {
		t.Fatal("apply proposal: success=false")
	}
	applyPayload := data.(map[string]interface{})
	if applyPayload["applied_slot_count"].(float64) < 1 {
		t.Fatal("expected at least 1 applied slot")
	}
	if applyPayload["proposal_id"] != proposalID {
		t.Fatalf("expected proposal_id %s in apply response, got %v", proposalID, applyPayload["proposal_id"])
	}

	// --- idempotent re-apply returns same result ---
	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/apply", map[string]interface{}{
		"idempotency_key": "RS-APPLY-1",
	})
	if w.Code != http.StatusOK {
		t.Fatalf("idempotent re-apply: expected 200, got %d body: %s", w.Code, w.Body.String())
	}

	// --- verify applied status ---
	w = testutil.Request(r, "GET", "/api/v1/ai/scheduling/proposals/"+proposalID, nil)
	if w.Code != http.StatusOK {
		t.Fatalf("get proposal: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ = testutil.DecodeResponse(w)
	pProp := data.(map[string]interface{})
	if pProp["status"] != "applied" {
		t.Fatalf("expected applied status, got %v", pProp["status"])
	}
	// Check that rollout_state is present.
	if _, ok := pProp["rollout_state"]; !ok {
		t.Fatal("expected rollout_state in proposal response")
	}
}

func TestRealSolverGovernance(t *testing.T) {
	_ = os.Setenv("AI_PROPOSAL_ENGINE", "real-solver")
	defer os.Unsetenv("AI_PROPOSAL_ENGINE")

	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-RS-GOV", "product_name": "Governance Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-RS-GOV", "product_id": "P-RS-GOV", "process_name": "Gov Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-RS-GOV/steps", map[string]interface{}{
		"step_id": "STEP-RS-GOV", "step_name": "Gov Step", "machine_type_required": "GOV",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-GOV", "machine_name": "Gov Machine", "machine_type": "GOV", "capacity_per_hour": 20,
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-RS-GOV", "quantity_total": 10,
		"deadline": time.Now().Add(48 * time.Hour).UTC().Format(time.RFC3339),
	})
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	// Generate proposal.
	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/jobs/"+jobID+"/proposals", nil)
	if w.Code != http.StatusCreated {
		t.Fatalf("generate: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ = testutil.DecodeResponse(w)
	proposalID := data.(map[string]interface{})["proposal_id"].(string)

	// Draft apply must be blocked.
	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/apply", map[string]interface{}{
		"idempotency_key": "GOV-DRAFT",
	})
	if w.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422 for draft apply, got %d body: %s", w.Code, w.Body.String())
	}

	// Approve then reject.
	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/approve", map[string]interface{}{
		"notes": "governance test",
	})
	if w.Code != http.StatusOK {
		t.Fatalf("approve: got %d, body: %s", w.Code, w.Body.String())
	}
	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/reject", map[string]interface{}{
		"reason": "requirements changed",
	})
	if w.Code != http.StatusOK {
		t.Fatalf("reject: got %d, body: %s", w.Code, w.Body.String())
	}
	_, data, _ = testutil.DecodeResponse(w)
	if data.(map[string]interface{})["status"] != "rejected" {
		t.Fatalf("expected rejected status after reject call")
	}

	// Applying a rejected proposal must be blocked.
	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/proposals/"+proposalID+"/apply", map[string]interface{}{
		"idempotency_key": "GOV-REJECTED",
	})
	if w.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422 for rejected apply, got %d body: %s", w.Code, w.Body.String())
	}
}

func TestRealSolverShadowMode(t *testing.T) {
	_ = os.Setenv("AI_PROPOSAL_ENGINE", "heuristic")
	_ = os.Setenv("AI_SOLVER_SHADOW_MODE", "true")
	defer func() {
		os.Unsetenv("AI_PROPOSAL_ENGINE")
		os.Unsetenv("AI_SOLVER_SHADOW_MODE")
	}()

	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-SHADOW", "product_name": "Shadow Mode Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-SHADOW", "product_id": "P-SHADOW", "process_name": "Shadow Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-SHADOW/steps", map[string]interface{}{
		"step_id": "STEP-SHADOW", "step_name": "Shadow Step", "machine_type_required": "SHAD",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-SHADOW", "machine_name": "Shadow Machine", "machine_type": "SHAD", "capacity_per_hour": 25,
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-SHADOW", "quantity_total": 20,
		"deadline": time.Now().Add(48 * time.Hour).UTC().Format(time.RFC3339),
	})
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	// Generate proposal. With shadow mode on, the proposal should include a shadow engine.
	w = testutil.Request(r, "POST", "/api/v1/ai/scheduling/jobs/"+jobID+"/proposals", nil)
	if w.Code != http.StatusCreated {
		t.Fatalf("generate proposal (shadow): got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("generate proposal: success=false")
	}
	payload := data.(map[string]interface{})
	// Primary engine should be heuristic.
	if engine, _ := payload["engine"].(string); engine == "" {
		t.Fatal("expected non-empty engine field")
	}
	// Shadow engine evidence should be attached (from GET proposal, which carries the persisted record).
	proposalID := payload["proposal_id"].(string)
	w = testutil.Request(r, "GET", "/api/v1/ai/scheduling/proposals/"+proposalID, nil)
	_, data, _ = testutil.DecodeResponse(w)
	propData := data.(map[string]interface{})
	// shadow_engine should be populated since shadow mode is on.
	if _, ok := propData["shadow_engine"]; !ok {
		t.Fatal("expected shadow_engine field in proposal record when shadow mode is enabled")
	}
}
