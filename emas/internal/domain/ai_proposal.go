package domain

import "time"

const (
	AIProposalStatusDraft    = "draft"
	AIProposalStatusApproved = "approved"
	AIProposalStatusRejected = "rejected"
	AIProposalStatusApplied  = "applied"
	AIProposalStatusStale    = "stale"
)

type AIProposal struct {
	ProposalID            string     `gorm:"column:proposal_id;primaryKey;size:50" json:"proposal_id"`
	JobID                 string     `gorm:"column:job_id;size:50;index;not null" json:"job_id"`
	Version               int        `gorm:"column:version;not null;default:1" json:"version"`
	Status                string     `gorm:"column:status;size:20;index;not null" json:"status"`
	RolloutState          string     `gorm:"column:rollout_state;size:40" json:"rollout_state"`
	Engine                string     `gorm:"column:engine;size:50" json:"engine"`
	EngineVersion         string     `gorm:"column:engine_version;size:50" json:"engine_version"`
	ObjectiveScore        float64    `gorm:"column:objective_score" json:"objective_score"`
	ShadowEngine          string     `gorm:"column:shadow_engine;size:50" json:"shadow_engine"`
	ShadowObjectiveScore  float64    `gorm:"column:shadow_objective_score" json:"shadow_objective_score"`
	FallbackReason        string     `gorm:"column:fallback_reason;type:text" json:"fallback_reason"`
	InputHash             string     `gorm:"column:input_hash;size:128;index" json:"input_hash"`
	IdempotencyKey        string     `gorm:"column:idempotency_key;size:100;index" json:"idempotency_key"`
	RiskLevel             string     `gorm:"column:risk_level;size:20" json:"risk_level"`
	RiskScore             float64    `gorm:"column:risk_score" json:"risk_score"`
	SummaryText           string     `gorm:"column:summary_text;type:text" json:"summary_text"`
	ProposalJSON          string     `gorm:"column:proposal_json;type:longtext" json:"proposal_json"`
	ShadowProposalJSON    string     `gorm:"column:shadow_proposal_json;type:longtext" json:"shadow_proposal_json"`
	SnapshotJSON          string     `gorm:"column:snapshot_json;type:longtext" json:"snapshot_json"`
	OutcomeJSON           string     `gorm:"column:outcome_json;type:longtext" json:"outcome_json"`
	OutcomeStatus         string     `gorm:"column:outcome_status;size:30" json:"outcome_status"`
	EstimatedCompletionAt *time.Time `gorm:"column:estimated_completion_at" json:"estimated_completion_at,omitempty"`
	ActualCompletionAt    *time.Time `gorm:"column:actual_completion_at" json:"actual_completion_at,omitempty"`
	EstimateDeviationMins int        `gorm:"column:estimate_deviation_mins" json:"estimate_deviation_mins"`
	ActualProducedQty     int        `gorm:"column:actual_produced_qty" json:"actual_produced_qty"`
	ActualScrapQty        int        `gorm:"column:actual_scrap_qty" json:"actual_scrap_qty"`
	ApprovalNotes         string     `gorm:"column:approval_notes;type:text" json:"approval_notes"`
	RejectionReason       string     `gorm:"column:rejection_reason;type:text" json:"rejection_reason"`
	GeneratedBy           string     `gorm:"column:generated_by;size:100" json:"generated_by"`
	ApprovedBy            string     `gorm:"column:approved_by;size:100" json:"approved_by"`
	RejectedBy            string     `gorm:"column:rejected_by;size:100" json:"rejected_by"`
	AppliedBy             string     `gorm:"column:applied_by;size:100" json:"applied_by"`
	GeneratedAt           time.Time  `gorm:"column:generated_at;index" json:"generated_at"`
	ApprovedAt            *time.Time `gorm:"column:approved_at" json:"approved_at,omitempty"`
	RejectedAt            *time.Time `gorm:"column:rejected_at" json:"rejected_at,omitempty"`
	AppliedAt             *time.Time `gorm:"column:applied_at" json:"applied_at,omitempty"`
	StaleDetectedAt       *time.Time `gorm:"column:stale_detected_at" json:"stale_detected_at,omitempty"`
	LastOutcomeRecordedAt *time.Time `gorm:"column:last_outcome_recorded_at" json:"last_outcome_recorded_at,omitempty"`
	CreatedAt             time.Time  `gorm:"column:created_at" json:"created_at"`
	UpdatedAt             time.Time  `gorm:"column:updated_at" json:"updated_at"`
}

func (AIProposal) TableName() string { return "ai_proposals" }
