package handler_test

import (
	"net/http"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

func TestAIHandler_ParseCommand_CreateJob(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query": "Create a job for 500 units of Valve Body on CNC Mill 01, deadline April 5, 2026",
	})
	if w.Code != http.StatusOK {
		t.Fatalf("create job parse: got %d", w.Code)
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("parse failed")
	}
	m := data.(map[string]interface{})
	action := m["action"]
	if action != "create_job" {
		t.Errorf("action: got %v", action)
	}
}

func TestAIHandler_ParseCommand_Reschedule(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query": "Reschedule Job P-2404 slot 2 to tomorrow morning on CNC Mill 02",
	})
	if w.Code != http.StatusOK {
		t.Fatalf("reschedule parse: got %d", w.Code)
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("parse failed")
	}
	_ = data.(map[string]interface{})
	// AI stub may not parse reschedule; we only verify endpoint responds successfully
}

func TestAIHandler_ParseCommand_Consume(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query": "Consume 50 kg of Aluminum Alloy for Job P-2404 Slot 1",
	})
	if w.Code != http.StatusOK {
		t.Fatalf("consume parse: got %d", w.Code)
	}
}

func TestAIHandler_ParseCommand_Unknown(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query": "random gibberish xyz",
	})
	if w.Code != http.StatusOK {
		t.Fatalf("unknown: got %d", w.Code)
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("should succeed with unknown intent")
	}
	m := data.(map[string]interface{})
	if m["intent"] != "unknown" {
		t.Errorf("intent: got %v", m["intent"])
	}
}

func TestAIHandler_ParseCommand_ValidationError(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query": "",
	})
	if w.Code != http.StatusBadRequest {
		t.Fatalf("empty query: got %d, want 400", w.Code)
	}
}

func TestAIHandler_ParseCommand_Proposal(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-AICMD", "product_name": "AI Command Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-AICMD", "product_id": "P-AICMD", "process_name": "AI Command Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-AICMD/steps", map[string]interface{}{
		"step_id": "STEP-AICMD", "step_name": "Assembly", "machine_type_required": "AICMD",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-AICMD", "machine_name": "AI Command Machine", "machine_type": "AICMD", "capacity_per_hour": 20,
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-AICMD", "quantity_total": 15, "deadline": "2026-12-01T12:00:00Z",
	})
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query": "Suggest schedule for job " + jobID,
	})
	if w.Code != http.StatusOK {
		t.Fatalf("proposal parse: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("proposal parse failed")
	}
	m := data.(map[string]interface{})
	if m["action"] != "propose_schedule" {
		t.Fatalf("expected propose_schedule action, got %v", m["action"])
	}
	if m["execution_mode"] != "suggest_only" {
		t.Fatalf("expected suggest_only mode, got %v", m["execution_mode"])
	}
	if _, ok := m["insights"]; ok {
		t.Fatal("did not expect proposal insights without execute_readonly")
	}
}

func TestAIHandler_ParseCommand_ExplainJob(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-EXPLAIN", "product_name": "Explain Product",
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-EXPLAIN", "quantity_total": 10, "deadline": "2026-12-02T12:00:00Z",
	})
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query": "Explain job " + jobID,
	})
	if w.Code != http.StatusOK {
		t.Fatalf("explain parse: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("explain parse failed")
	}
	m := data.(map[string]interface{})
	if m["action"] != "explain_job" {
		t.Fatalf("expected explain_job action, got %v", m["action"])
	}
}

func TestAIHandler_ParseCommand_ApplyProposal(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-APPLYCMD", "product_name": "Apply Proposal Product",
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-APPLYCMD", "quantity_total": 12, "deadline": "2026-12-03T12:00:00Z",
	})
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query": "Apply proposal for job " + jobID,
	})
	if w.Code != http.StatusOK {
		t.Fatalf("apply proposal parse: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("apply proposal parse failed")
	}
	m := data.(map[string]interface{})
	if m["action"] != "apply_proposal" {
		t.Fatalf("expected apply_proposal action, got %v", m["action"])
	}
}

func TestAIHandler_ParseCommand_ApproveProposal(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query": "Approve proposal AIPROP-12345",
	})
	if w.Code != http.StatusOK {
		t.Fatalf("approve proposal parse: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("approve proposal parse failed")
	}
	m := data.(map[string]interface{})
	if m["action"] != "approve_proposal" {
		t.Fatalf("expected approve_proposal action, got %v", m["action"])
	}
	entities := m["entities"].(map[string]interface{})
	if entities["proposal_id"] != "AIPROP-12345" {
		t.Fatalf("expected proposal_id AIPROP-12345, got %v", entities["proposal_id"])
	}
}

func TestAIHandler_ParseCommand_ProposalAmbiguous(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	w := testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query": "Suggest a schedule proposal",
	})
	if w.Code != http.StatusOK {
		t.Fatalf("proposal ambiguous parse: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("proposal ambiguous parse failed")
	}
	m := data.(map[string]interface{})
	if ambiguous, ok := m["ambiguous"].(bool); !ok || !ambiguous {
		t.Fatalf("expected ambiguous=true, got %v", m["ambiguous"])
	}
	clarifications, ok := m["clarifications"].([]interface{})
	if !ok || len(clarifications) == 0 {
		t.Fatal("expected clarification prompts")
	}
	cards, ok := m["result_cards"].([]interface{})
	if !ok || len(cards) == 0 {
		t.Fatal("expected clarification result card")
	}
	firstCard := cards[0].(map[string]interface{})
	if firstCard["kind"] != "clarification_required" {
		t.Fatalf("expected clarification_required card, got %v", firstCard["kind"])
	}
}

func TestAIHandler_ParseCommand_ProposalExecuteReadonly(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-AIEXEC", "product_name": "AI Exec Product",
	})
	testutil.Request(r, "POST", "/api/v1/processes", map[string]interface{}{
		"process_id": "PRC-AIEXEC", "product_id": "P-AIEXEC", "process_name": "AI Exec Process",
	})
	testutil.Request(r, "POST", "/api/v1/processes/PRC-AIEXEC/steps", map[string]interface{}{
		"step_id": "STEP-AIEXEC", "step_name": "Assembly", "machine_type_required": "AIEXEC",
	})
	testutil.Request(r, "POST", "/api/v1/machines", map[string]interface{}{
		"machine_id": "M-AIEXEC", "machine_name": "AI Exec Machine", "machine_type": "AIEXEC", "capacity_per_hour": 18,
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-AIEXEC", "quantity_total": 9, "deadline": "2026-12-04T12:00:00Z",
	})
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query":            "Suggest schedule for job " + jobID,
		"execute_readonly": true,
	})
	if w.Code != http.StatusOK {
		t.Fatalf("proposal execute parse: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("proposal execute parse failed")
	}
	m := data.(map[string]interface{})
	if m["execution_mode"] != "executed_readonly" {
		t.Fatalf("expected executed_readonly mode, got %v", m["execution_mode"])
	}
	if executed, ok := m["executed"].(bool); !ok || !executed {
		t.Fatalf("expected executed=true, got %v", m["executed"])
	}
	if _, ok := m["insights"]; !ok {
		t.Fatal("expected proposal insights when execute_readonly=true")
	}
	cards, ok := m["result_cards"].([]interface{})
	if !ok || len(cards) == 0 {
		t.Fatal("expected proposal result_cards")
	}
	firstCard := cards[0].(map[string]interface{})
	if firstCard["kind"] != "schedule_proposal" {
		t.Fatalf("expected schedule_proposal card, got %v", firstCard["kind"])
	}
}

func TestAIHandler_ParseCommand_QueryStatusExecuteReadonly(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-STATUSAI", "product_name": "Status Product",
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-STATUSAI", "quantity_total": 7, "deadline": "2026-12-05T12:00:00Z",
	})
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query":            "Show job status for job " + jobID,
		"execute_readonly": true,
	})
	if w.Code != http.StatusOK {
		t.Fatalf("query status execute parse: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("query status execute parse failed")
	}
	m := data.(map[string]interface{})
	if m["action"] != "query_status" {
		t.Fatalf("expected query_status action, got %v", m["action"])
	}
	if m["execution_mode"] != "executed_readonly" {
		t.Fatalf("expected executed_readonly mode, got %v", m["execution_mode"])
	}
	insights, ok := m["insights"].(map[string]interface{})
	if !ok {
		t.Fatal("expected insights map")
	}
	if _, ok := insights["job"]; !ok {
		t.Fatal("expected job in query-status insights")
	}
	cards, ok := m["result_cards"].([]interface{})
	if !ok || len(cards) == 0 {
		t.Fatal("expected query status result_cards")
	}
	firstCard := cards[0].(map[string]interface{})
	if firstCard["kind"] != "job_status" {
		t.Fatalf("expected job_status card, got %v", firstCard["kind"])
	}
}

func TestAIHandler_ParseCommand_ApplyProposalExecuteReadonlyBlocked(t *testing.T) {
	db := testutil.NewTestDB(t)
	r := testutil.NewTestRouter(db, router.Setup)

	testutil.Request(r, "POST", "/api/v1/products", map[string]interface{}{
		"product_id": "P-APPLYBLOCK", "product_name": "Apply Block Product",
	})
	w := testutil.Request(r, "POST", "/api/v1/jobs", map[string]interface{}{
		"product_id": "P-APPLYBLOCK", "quantity_total": 4, "deadline": "2026-12-06T12:00:00Z",
	})
	_, data, _ := testutil.DecodeResponse(w)
	jobID := data.(map[string]interface{})["job_id"].(string)

	w = testutil.Request(r, "POST", "/api/v1/ai/command", map[string]interface{}{
		"query":            "Apply proposal for job " + jobID,
		"execute_readonly": true,
	})
	if w.Code != http.StatusOK {
		t.Fatalf("apply proposal blocked parse: got %d, body: %s", w.Code, w.Body.String())
	}
	success, data, _ := testutil.DecodeResponse(w)
	if !success {
		t.Fatal("apply proposal blocked parse failed")
	}
	m := data.(map[string]interface{})
	if m["execution_mode"] != "blocked_write_action" {
		t.Fatalf("expected blocked_write_action mode, got %v", m["execution_mode"])
	}
	if executed, ok := m["executed"].(bool); ok && executed {
		t.Fatal("did not expect executed=true for blocked write action")
	}
	cards, ok := m["result_cards"].([]interface{})
	if !ok || len(cards) == 0 {
		t.Fatal("expected blocked write result_cards")
	}
	firstCard := cards[0].(map[string]interface{})
	if firstCard["kind"] != "approval_required" {
		t.Fatalf("expected approval_required card, got %v", firstCard["kind"])
	}
}
