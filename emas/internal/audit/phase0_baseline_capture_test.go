package audit_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"emas/internal/router"
	"emas/internal/testutil"
)

type baselineResponseSample struct {
	Method     string          `json:"method"`
	Path       string          `json:"path"`
	StatusCode int             `json:"status_code"`
	Body       json.RawMessage `json:"body"`
}

func TestCapturePhase0BaselineResponses(t *testing.T) {
	if os.Getenv("EMAS_CAPTURE_PHASE0_BASELINE") != "1" {
		t.Skip("set EMAS_CAPTURE_PHASE0_BASELINE=1 to regenerate Phase 0 baseline response samples")
	}

	db := testutil.NewTestDB(t)
	testutil.SeedCanonical(t, db)
	r := testutil.NewTestRouter(db, router.Setup)

	outDir := filepath.Join(repoRoot(t), "docs", "audit", "phase0", "api_responses")
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		t.Fatalf("create output directory: %v", err)
	}

	samples := map[string]string{
		"jobs_list_fields.json":            "/api/v1/jobs?fields=job_id,product_id,status,priority,deadline&sort_by=deadline&sort_dir=asc&limit=3",
		"machines_list_fields.json":        "/api/v1/machines?fields=machine_id,machine_name,machine_type,status&sort_by=machine_id&sort_dir=asc&limit=3",
		"inventory_materials_list.json":    "/api/v1/inventory/materials?sort_by=material_name&sort_dir=asc&limit=3",
		"scheduling_readiness.json":        "/api/v1/scheduling/products/P-001/readiness",
		"ai_job_proposals_list.json":       "/api/v1/ai/scheduling/jobs/JOB-SEED-001/proposals",
		"ai_proposal_detail_seed_001.json": "/api/v1/ai/scheduling/proposals/AIPROP-SEED-001",
	}

	for filename, path := range samples {
		w := testutil.Request(r, http.MethodGet, path, nil)
		if w.Code >= http.StatusInternalServerError {
			t.Fatalf("%s returned %d: %s", path, w.Code, w.Body.String())
		}

		var body json.RawMessage
		if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
			t.Fatalf("%s returned non-JSON body: %v", path, err)
		}

		payload := baselineResponseSample{
			Method:     http.MethodGet,
			Path:       path,
			StatusCode: w.Code,
			Body:       body,
		}
		raw, err := json.Marshal(payload)
		if err != nil {
			t.Fatalf("marshal %s: %v", filename, err)
		}

		var pretty bytes.Buffer
		if err := json.Indent(&pretty, raw, "", "  "); err != nil {
			t.Fatalf("format %s: %v", filename, err)
		}
		pretty.WriteByte('\n')

		if err := os.WriteFile(filepath.Join(outDir, filename), pretty.Bytes(), 0o644); err != nil {
			t.Fatalf("write %s: %v", filename, err)
		}
	}
}

func repoRoot(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
}
