package repository

import (
	"emas/internal/domain"
	"time"

	"gorm.io/gorm"
)

type AIProposalRepository struct {
	db *gorm.DB
}

func NewAIProposalRepository(db *gorm.DB) *AIProposalRepository {
	return &AIProposalRepository{db: db}
}

func (r *AIProposalRepository) Create(p *domain.AIProposal) error {
	return r.db.Create(p).Error
}

func (r *AIProposalRepository) GetByID(id string) (*domain.AIProposal, error) {
	var proposal domain.AIProposal
	if err := r.db.Where("proposal_id = ?", id).First(&proposal).Error; err != nil {
		return nil, err
	}
	return &proposal, nil
}

func (r *AIProposalRepository) ListByJobID(jobID string) ([]domain.AIProposal, error) {
	var proposals []domain.AIProposal
	err := r.db.Where("job_id = ?", jobID).Order("version DESC, created_at DESC").Find(&proposals).Error
	return proposals, err
}

func (r *AIProposalRepository) LatestByJobID(jobID string) (*domain.AIProposal, error) {
	var proposal domain.AIProposal
	if err := r.db.Where("job_id = ?", jobID).Order("version DESC, created_at DESC").First(&proposal).Error; err != nil {
		return nil, err
	}
	return &proposal, nil
}

func (r *AIProposalRepository) LatestByJobIDWithStatuses(jobID string, statuses []string) (*domain.AIProposal, error) {
	var proposal domain.AIProposal
	if err := r.db.Where("job_id = ? AND status IN ?", jobID, statuses).Order("version DESC, created_at DESC").First(&proposal).Error; err != nil {
		return nil, err
	}
	return &proposal, nil
}

func (r *AIProposalRepository) NextVersion(jobID string) (int, error) {
	var results []domain.AIProposal
	err := r.db.Where("job_id = ?", jobID).Order("version DESC").Limit(1).Find(&results).Error
	if err != nil {
		return 0, err
	}
	if len(results) == 0 {
		return 1, nil
	}
	return results[0].Version + 1, nil
}

func (r *AIProposalRepository) Update(p *domain.AIProposal) error {
	return r.db.Save(p).Error
}

func (r *AIProposalRepository) DeleteByJobID(jobID string) error {
	return r.db.Where("job_id = ?", jobID).Delete(&domain.AIProposal{}).Error
}

func (r *AIProposalRepository) MarkOtherDraftsStale(jobID, keepProposalID string, staleAt interface{}) error {
	q := r.db.Model(&domain.AIProposal{}).
		Where("job_id = ? AND proposal_id <> ? AND status IN ?", jobID, keepProposalID, []string{domain.AIProposalStatusDraft, domain.AIProposalStatusApproved}).
		Updates(map[string]interface{}{
			"status":            domain.AIProposalStatusStale,
			"stale_detected_at": staleAt,
			"updated_at":        staleAt,
		})
	if q.Error != nil {
		return q.Error
	}
	return nil
}

func (r *AIProposalRepository) DB() *gorm.DB {
	return r.db
}

type ProposalMetricsSummary struct {
	ProposalGenerated        int       `json:"proposal_generated"`
	ProposalApproved         int       `json:"proposal_approved"`
	ProposalRejected         int       `json:"proposal_rejected"`
	ProposalApplied          int       `json:"proposal_applied"`
	ProposalStale            int       `json:"proposal_stale"`
	ProposalApplyFailures    int       `json:"proposal_apply_failures"`
	SolverExecutions         int       `json:"solver_executions"`
	HeuristicExecutions      int       `json:"heuristic_executions"`
	SolverShadowSamples      int       `json:"solver_shadow_samples"`
	AcceptanceRate           float64   `json:"acceptance_rate"`
	AvgEstimateDeviationMins float64   `json:"avg_estimate_deviation_mins"`
	AvgScrapQty              float64   `json:"avg_scrap_qty"`
	UpdatedAt                time.Time `json:"updated_at"`
}

func (r *AIProposalRepository) MetricsSummary() (*ProposalMetricsSummary, error) {
	var summary ProposalMetricsSummary
	var generated int64
	if err := r.db.Model(&domain.AIProposal{}).Count(&generated).Error; err != nil {
		return nil, err
	}
	statusCount := func(status string) (int64, error) {
		var count int64
		err := r.db.Model(&domain.AIProposal{}).Where("status = ?", status).Count(&count).Error
		return count, err
	}
	approved, err := statusCount(domain.AIProposalStatusApproved)
	if err != nil {
		return nil, err
	}
	rejected, err := statusCount(domain.AIProposalStatusRejected)
	if err != nil {
		return nil, err
	}
	applied, err := statusCount(domain.AIProposalStatusApplied)
	if err != nil {
		return nil, err
	}
	stale, err := statusCount(domain.AIProposalStatusStale)
	if err != nil {
		return nil, err
	}
	var solverExecutions int64
	if err := r.db.Model(&domain.AIProposal{}).Where("engine LIKE ?", "%solver%").Count(&solverExecutions).Error; err != nil {
		return nil, err
	}
	var heuristicExecutions int64
	if err := r.db.Model(&domain.AIProposal{}).Where("engine = ?", "heuristic").Count(&heuristicExecutions).Error; err != nil {
		return nil, err
	}
	var shadowSamples int64
	if err := r.db.Model(&domain.AIProposal{}).Where("shadow_engine <> ''").Count(&shadowSamples).Error; err != nil {
		return nil, err
	}
	type aggregates struct {
		AvgDeviation float64
		AvgScrap     float64
	}
	var agg aggregates
	if err := r.db.Model(&domain.AIProposal{}).
		Select("COALESCE(AVG(estimate_deviation_mins),0) AS avg_deviation, COALESCE(AVG(actual_scrap_qty),0) AS avg_scrap").
		Where("actual_completion_at IS NOT NULL").
		Scan(&agg).Error; err != nil {
		return nil, err
	}
	summary = ProposalMetricsSummary{
		ProposalGenerated:        int(generated),
		ProposalApproved:         int(approved),
		ProposalRejected:         int(rejected),
		ProposalApplied:          int(applied),
		ProposalStale:            int(stale),
		ProposalApplyFailures:    int(rejected + stale), // baseline persisted failures; explicit service failures are added at runtime
		SolverExecutions:         int(solverExecutions),
		HeuristicExecutions:      int(heuristicExecutions),
		SolverShadowSamples:      int(shadowSamples),
		AvgEstimateDeviationMins: agg.AvgDeviation,
		AvgScrapQty:              agg.AvgScrap,
		UpdatedAt:                time.Now().UTC(),
	}
	if generated > 0 {
		summary.AcceptanceRate = float64(applied) / float64(generated)
	}
	return &summary, nil
}
