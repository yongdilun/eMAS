package schedulereval

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"time"

	"emas/internal/service"
	"emas/pkg/featureflags"
)

type HTTPRunner struct {
	Handler http.Handler
	Headers map[string]string
	OrderBy string
}

type RunRequest struct {
	ScenarioID              string
	Endpoint                string
	SchedulerProfile        string
	IncludeInventoryActions bool
	DryRun                  bool
	GitSHA                  string
	SeedFingerprint         string
}

func (r HTTPRunner) Run(ctx context.Context, req RunRequest) (EndpointResult, error) {
	if r.Handler == nil {
		return EndpointResult{}, errors.New("scheduler eval runner requires an HTTP handler")
	}
	endpoint := req.Endpoint
	if endpoint == "" {
		endpoint = EndpointBatchProposals
	}
	orderBy := r.OrderBy
	if orderBy == "" {
		orderBy = featureflags.DefaultBatchOrderBy
	}
	path, body, dryRun, err := requestForEndpoint(endpoint, orderBy, req.IncludeInventoryActions, req.DryRun)
	if err != nil {
		return EndpointResult{}, err
	}
	started := time.Now()
	raw, err := r.do(ctx, http.MethodPost, path, body)
	elapsed := time.Since(started)
	if err != nil {
		return EndpointResult{}, err
	}
	data, err := decodeSchedulingData(raw)
	if err != nil {
		return EndpointResult{}, err
	}
	return EndpointResult{
		Metadata: RunMetadata{
			GitSHA:           req.GitSHA,
			SchedulerProfile: req.SchedulerProfile,
			ScenarioID:       req.ScenarioID,
			SeedFingerprint:  req.SeedFingerprint,
			Endpoint:         endpoint,
			OrderBy:          orderBy,
			DryRun:           dryRun,
			Timestamp:        time.Now().UTC(),
			SchedulerEngine:  firstProposalEngine(data.Proposals),
			SchedulerVersion: firstProposalEngineVersion(data.Proposals),
		},
		Proposals: data.Proposals,
		Summary:   data.Summary,
		Runtime:   elapsed,
		Partial:   data.Partial,
	}, nil
}

func (r HTTPRunner) RunScorecard(ctx context.Context, req RunRequest, opts EvaluateOptions) (Scorecard, error) {
	result, err := r.Run(ctx, req)
	if err != nil {
		return Scorecard{}, err
	}
	score := Evaluate(result, opts)
	if scenario, ok := ScenarioByID(req.ScenarioID); ok {
		for _, finding := range ValidateScenarioExpectation(score, scenario.Expect) {
			score.Failures = append(score.Failures, finding)
		}
	}
	score.RecalculateScore()
	return score, nil
}

func (r HTTPRunner) RunOneShotResolution(ctx context.Context, req RunRequest, opts EvaluateOptions) (Scorecard, error) {
	req.Endpoint = EndpointBatchProposals
	req.IncludeInventoryActions = true
	initial, err := r.Run(ctx, req)
	if err != nil {
		return Scorecard{}, err
	}
	if initial.Summary != nil && len(initial.Summary.MaterialReplenishmentAggregate) > 0 {
		if err := r.applyAggregate(ctx, initial.Summary.MaterialReplenishmentAggregate); err != nil {
			return Scorecard{}, err
		}
	}
	req.Endpoint = EndpointRescheduleAll
	req.DryRun = true
	final, err := r.Run(ctx, req)
	if err != nil {
		return Scorecard{}, err
	}
	final.Metadata.ScenarioID = ScenarioOneShotResolution
	score := Evaluate(final, opts)
	if scenario, ok := ScenarioByID(ScenarioOneShotResolution); ok {
		for _, finding := range ValidateScenarioExpectation(score, scenario.Expect) {
			score.Failures = append(score.Failures, finding)
		}
	}
	score.RecalculateScore()
	return score, nil
}

func (r HTTPRunner) applyAggregate(ctx context.Context, lines []service.BatchMaterialReplenishmentLine) error {
	suggestions := make([]map[string]interface{}, 0, len(lines))
	for _, line := range lines {
		if line.MaterialID == "" || line.RecommendedQty <= 0 || line.SuggestedArriveAt.IsZero() {
			continue
		}
		suggestions = append(suggestions, map[string]interface{}{
			"option_type": "replenish",
			"material_id": line.MaterialID,
			"quantity":    line.RecommendedQty,
			"arrive_at":   line.SuggestedArriveAt.Format(time.RFC3339Nano),
			"notes":       "scheduler_eval one-shot material resolution",
		})
	}
	if len(suggestions) == 0 {
		return nil
	}
	_, err := r.do(ctx, http.MethodPost, "/api/v1/ai/scheduling/apply-replenishment-batch", map[string]interface{}{
		"suggestions": suggestions,
		"order_by":    firstNonEmpty(r.OrderBy, featureflags.DefaultBatchOrderBy),
	})
	return err
}

func requestForEndpoint(endpoint, orderBy string, includeInventoryActions bool, dryRun bool) (string, map[string]interface{}, bool, error) {
	switch endpoint {
	case EndpointBatchProposals:
		return "/api/v1/ai/scheduling/batch-proposals", map[string]interface{}{
			"scope":                     "all_unscheduled",
			"order_by":                  orderBy,
			"include_inventory_actions": includeInventoryActions,
		}, false, nil
	case EndpointRescheduleAll:
		return "/api/v1/ai/scheduling/reschedule-all", map[string]interface{}{
			"order_by": orderBy,
			"dry_run":  dryRun,
		}, dryRun, nil
	default:
		return "", nil, false, fmt.Errorf("unknown scheduler eval endpoint %q", endpoint)
	}
}

func (r HTTPRunner) do(ctx context.Context, method, path string, body interface{}) ([]byte, error) {
	var bodyReader *bytes.Reader
	if body != nil {
		payload, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		bodyReader = bytes.NewReader(payload)
	} else {
		bodyReader = bytes.NewReader(nil)
	}
	req := httptest.NewRequest(method, path, bodyReader).WithContext(ctx)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for key, value := range r.Headers {
		req.Header.Set(key, value)
	}
	w := httptest.NewRecorder()
	r.Handler.ServeHTTP(w, req)
	if w.Code < 200 || w.Code >= 300 {
		return nil, fmt.Errorf("%s %s returned %d: %s", method, path, w.Code, strings.TrimSpace(w.Body.String()))
	}
	return w.Body.Bytes(), nil
}

type apiResponse struct {
	Success bool            `json:"success"`
	Data    json.RawMessage `json:"data"`
	Error   string          `json:"error"`
}

type schedulingData struct {
	Proposals []*service.SchedulingProposal `json:"proposals"`
	Summary   *service.BatchProposalSummary `json:"summary"`
	Partial   bool                          `json:"partial"`
	Message   string                        `json:"message,omitempty"`
}

func decodeSchedulingData(raw []byte) (schedulingData, error) {
	var resp apiResponse
	if err := json.Unmarshal(raw, &resp); err != nil {
		return schedulingData{}, err
	}
	if !resp.Success {
		return schedulingData{}, fmt.Errorf("scheduler API success=false: %s", resp.Error)
	}
	var data schedulingData
	if err := json.Unmarshal(resp.Data, &data); err != nil {
		return schedulingData{}, err
	}
	return data, nil
}

func firstProposalEngine(proposals []*service.SchedulingProposal) string {
	for _, p := range proposals {
		if p != nil && p.Engine != "" {
			return p.Engine
		}
	}
	return ""
}

func firstProposalEngineVersion(proposals []*service.SchedulingProposal) string {
	for _, p := range proposals {
		if p != nil && p.EngineVersion != "" {
			return p.EngineVersion
		}
	}
	return ""
}
