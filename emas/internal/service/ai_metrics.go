package service

import "sync"

type AIMetrics struct {
	mu                       sync.Mutex
	ProposalGenerated        int     `json:"proposal_generated"`
	ProposalApproved         int     `json:"proposal_approved"`
	ProposalRejected         int     `json:"proposal_rejected"`
	ProposalApplied          int     `json:"proposal_applied"`
	ProposalStale            int     `json:"proposal_stale"`
	ProposalApplyFailures    int     `json:"proposal_apply_failures"`
	ReadonlyExecutions       int     `json:"readonly_executions"`
	SolverExecutions         int     `json:"solver_executions"`
	HeuristicExecutions      int     `json:"heuristic_executions"`
	SolverFallbacks          int     `json:"solver_fallbacks"`
	SolverShadowSamples      int     `json:"solver_shadow_samples"`
	AcceptanceRate           float64 `json:"acceptance_rate"`
	AvgEstimateDeviationMins float64 `json:"avg_estimate_deviation_mins"`
	AvgScrapQty              float64 `json:"avg_scrap_qty"`
	RolloutState             string  `json:"rollout_state"`
	KpiGatePassed            bool    `json:"kpi_gate_passed"`
}

func NewAIMetrics() *AIMetrics {
	return &AIMetrics{}
}

func (m *AIMetrics) Snapshot() AIMetrics {
	m.mu.Lock()
	defer m.mu.Unlock()
	return *m
}

func (m *AIMetrics) Inc(field *int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	*field = *field + 1
}
