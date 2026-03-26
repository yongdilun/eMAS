package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

type MLRiskRequest struct {
	JobID       string `json:"job_id"`
	ProductID   string `json:"product_id"`
	JobPriority string `json:"job_priority,omitempty"`

	MaterialShortageCount   int   `json:"material_shortage_count"`
	SubProductShortageCount int   `json:"sub_product_shortage_count"`
	CanStartNow             *bool `json:"can_start_now,omitempty"`

	Now                 string `json:"now,omitempty"`
	Deadline            string `json:"deadline,omitempty"`
	EstimatedCompletion string `json:"estimated_completion,omitempty"`

	SnapshotMachineIDs       []string  `json:"snapshot_machine_ids"`
	QueueLengthsVector       []int     `json:"queue_lengths_vector"`
	MachineUtilizationVector []float64 `json:"machine_utilization_vector"`
}

type MLRiskResponse struct {
	ProbabilityOfDelay    float64 `json:"probability_of_delay"`
	DelaySeverity         string  `json:"delay_severity"`
	PredictedDelayMinutes int     `json:"predicted_delay_minutes"`
	ModelVersion          string  `json:"model_version"`
	LatencyMs             float64 `json:"latency_ms"`
}

type MLInferenceClient struct {
	baseURL    string
	httpClient *http.Client
}

func DefaultMLBaseURL() string {
	v := strings.TrimSpace(os.Getenv("ML_API_BASE_URL"))
	if v == "" {
		return "http://127.0.0.1:9009"
	}
	return v
}

func NewMLInferenceClient(baseURL string, timeout time.Duration) (*MLInferenceClient, error) {
	baseURL = strings.TrimSpace(baseURL)
	if baseURL == "" {
		return nil, errors.New("ml base url is empty")
	}
	if _, err := url.Parse(baseURL); err != nil {
		return nil, err
	}
	if timeout <= 0 {
		timeout = 45 * time.Millisecond
	}
	return &MLInferenceClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: timeout,
		},
	}, nil
}

func (c *MLInferenceClient) PredictDelayRisk(ctx context.Context, req *MLRiskRequest) (*MLRiskResponse, time.Duration, error) {
	if c == nil || c.httpClient == nil {
		return nil, 0, errors.New("ml client not configured")
	}
	if req == nil {
		return nil, 0, errors.New("nil request")
	}
	body, err := json.Marshal(req)
	if err != nil {
		return nil, 0, err
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(c.baseURL, "/")+"/predict-delay-risk", bytes.NewReader(body))
	if err != nil {
		return nil, 0, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	start := time.Now()
	resp, err := c.httpClient.Do(httpReq)
	latency := time.Since(start)
	if err != nil {
		return nil, latency, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, latency, errors.New("ml api non-2xx response")
	}
	var out MLRiskResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, latency, err
	}
	return &out, latency, nil
}

