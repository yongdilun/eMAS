package service

import (
	"context"
	"emas/internal/domain"
	"emas/internal/repository"
	"emas/pkg/featureflags"
	"emas/pkg/id"
	"emas/pkg/logger"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"

	"go.uber.org/zap"
	"gorm.io/gorm"
)

type snapshotVectors struct {
	MachineIDs               []string  `json:"machine_ids"`
	QueueLengthsVector       []int     `json:"queue_lengths_vector"`
	MachineUtilizationVector []float64 `json:"machine_utilization_vector"`
}

const mlDelayRiskConfidenceThreshold = 0.60

type HighRiskJobPrediction struct {
	JobID        string  `json:"job_id"`
	MachineName  string  `json:"machine_name"`
	Issue        string  `json:"issue"`
	RiskLevel    string  `json:"risk_level"`
	RiskScore    float64 `json:"risk_score"`
	DelayMinutes int     `json:"delay_minutes"`
}

type AIRecommendation struct {
	Icon     string `json:"icon"`
	Title    string `json:"title"`
	Action   string `json:"action"`
	Severity string `json:"severity,omitempty"`
}

type ForecastPoint struct {
	Label string  `json:"label"`
	Value float64 `json:"value"`
}

type ForecastSeries struct {
	Type string          `json:"type"`
	Data []ForecastPoint `json:"data"`
}

type ConfidenceSummary struct {
	ConfidencePct float64 `json:"confidence_pct"`
	Model         string  `json:"model"`
	LastTrained   string  `json:"last_trained"`
}

type SplitSuggestion struct {
	JobStepID          string    `json:"job_step_id"`
	RecommendedSplits  int       `json:"recommended_splits"`
	AllocationPercents []float64 `json:"allocation_percents"`
	IsParallel         bool      `json:"is_parallel"`
	Reason             string    `json:"reason"`
}

type DelayRiskDetail struct {
	JobID               string     `json:"job_id"`
	ProductID           string     `json:"product_id"`
	RiskLevel           string     `json:"risk_level"`
	RiskScore           float64    `json:"risk_score"`
	ProbabilityOfDelay  float64    `json:"probability_of_delay,omitempty"`
	DelaySeverity       string     `json:"delay_severity,omitempty"`
	PredictedDelayMins  int        `json:"predicted_delay_minutes,omitempty"`
	RiskSource          string     `json:"risk_source,omitempty"` // "ml" | "heuristic_fallback"
	Issue               string     `json:"issue"`
	DelayMinutes        int        `json:"delay_minutes"`
	Deadline            time.Time  `json:"deadline"`
	EarliestReadyAt     *time.Time `json:"earliest_ready_at,omitempty"`
	EstimatedCompletion *time.Time `json:"estimated_completion,omitempty"`
	Reasons             []string   `json:"reasons"`
}

type RankedMachineCandidate struct {
	Rank                  int       `json:"rank"`
	MachineID             string    `json:"machine_id"`
	MachineName           string    `json:"machine_name"`
	MachineType           string    `json:"machine_type"`
	Available             bool      `json:"available"`
	AvailableFrom         time.Time `json:"available_from"`
	EfficiencyFactor      float64   `json:"efficiency_factor"`
	CapacityPerHour       int       `json:"capacity_per_hour"`
	EstimatedDurationMins int       `json:"estimated_duration_mins"`
	Score                 float64   `json:"score"`
	Reasons               []string  `json:"reasons,omitempty"`
	Explanation           []string  `json:"explanation"`
}

type MachineRankingResult struct {
	JobStepID   string                   `json:"job_step_id"`
	StepID      string                   `json:"step_id"`
	StepName    string                   `json:"step_name"`
	WindowStart time.Time                `json:"window_start"`
	WindowEnd   time.Time                `json:"window_end"`
	Candidates  []RankedMachineCandidate `json:"candidates"`
}

type BottleneckForecastEntry struct {
	MachineID        string   `json:"machine_id"`
	MachineName      string   `json:"machine_name"`
	MachineType      string   `json:"machine_type"`
	Status           string   `json:"status"`
	UpcomingSlots    int      `json:"upcoming_slots"`
	ScheduledMinutes int      `json:"scheduled_minutes"`
	UtilizationRate  float64  `json:"utilization_rate"`
	LoadScore        float64  `json:"load_score"`
	AtRisk           bool     `json:"at_risk"`
	Reasons          []string `json:"reasons"`
}

type BottleneckForecastResult struct {
	DaysAhead   int                       `json:"days_ahead"`
	GeneratedAt time.Time                 `json:"generated_at"`
	Entries     []BottleneckForecastEntry `json:"entries"`
}

type SchedulingExplanation struct {
	JobID              string    `json:"job_id"`
	Summary            string    `json:"summary"`
	KeyPoints          []string  `json:"key_points"`
	RecommendedActions []string  `json:"recommended_actions"`
	GeneratedAt        time.Time `json:"generated_at"`
}

type ProposedSlot struct {
	JobStepID             string    `json:"job_step_id"`
	StepID                string    `json:"step_id"`
	StepName              string    `json:"step_name"`
	MachineID             string    `json:"machine_id"`
	MachineName           string    `json:"machine_name"`
	ScheduledStart        time.Time `json:"scheduled_start"`
	ScheduledEnd          time.Time `json:"scheduled_end"`
	QuantityPlanned       int       `json:"quantity_planned"`
	AllocationPercent     float64   `json:"allocation_percent"`
	IsParallel            bool      `json:"is_parallel"`
	BatchSequence         int       `json:"batch_sequence"`
	ActualDurationMins    int       `json:"actual_duration_mins,omitempty"`
	EstimatedDurationMins int       `json:"estimated_duration_mins"`
	ReservedDurationMins  int       `json:"reserved_duration_mins,omitempty"`
	RoundingOverheadMins  int       `json:"rounding_overhead_mins,omitempty"`
	Reasoning             []string  `json:"reasoning"`
}

type ProposalExplanation struct {
	Required          float64 `json:"required"`
	Available         float64 `json:"available"`
	PlannedProduction float64 `json:"planned_production"`
}

type InventorySnapshot struct {
	MaterialID string    `json:"material_id"`
	Version    string    `json:"version"`
	ComputedAt time.Time `json:"computed_at"`
}

type ReplenishmentSuggestion struct {
	MaterialID              string    `json:"material_id"`
	MaterialName            string    `json:"material_name"`
	SuggestedQty            float64   `json:"suggested_qty"`
	SuggestedArriveAt       time.Time `json:"suggested_arrive_at"`
	EarliestPossibleArrival time.Time `json:"earliest_possible_arrival"`
	IsLeadTimeConstrained   bool      `json:"is_lead_time_constrained"`
	SafetyBufferMins        int       `json:"safety_buffer_mins"`
	LeadTimeHours           int       `json:"lead_time_hours"`
	MergedFromCount         int       `json:"merged_from_count"`
	Rationale               string    `json:"rationale"`
}

type ShortageResolutionOption struct {
	RecommendationID      string                   `json:"recommendation_id,omitempty"`
	MaterialID            string                   `json:"material_id"`
	OptionType            string                   `json:"option_type"`
	Priority              int                      `json:"priority"`
	Description           string                   `json:"description"`
	ImpactSummary         string                   `json:"impact_summary"`
	Replenishment         *ReplenishmentSuggestion `json:"replenishment,omitempty"`
	EarliestFeasibleStart *time.Time               `json:"earliest_feasible_start,omitempty"`
	AffectedJobIDs        []string                 `json:"affected_job_ids,omitempty"`
	// DependencyProductID links a material-level replenish option to a subproduct shortage (schedule_production row).
	DependencyProductID string `json:"dependency_product_id,omitempty"`
	IsActionable        bool   `json:"is_actionable"`
	QualityFlags        []string `json:"quality_flags,omitempty"`
}

type PartialFeasibilityPlan struct {
	FeasibleQty          float64    `json:"feasible_qty"`
	DeferredQty          float64    `json:"deferred_qty"`
	DeferredUntil        *time.Time `json:"deferred_until,omitempty"`
	BlockingMaterials    []string   `json:"blocking_materials"`
	DeferredPlanningNode string     `json:"deferred_planning_node_key"`
}

type DeferredPlanningNode struct {
	PlanKey           string    `json:"plan_key"`
	ParentJobID       string    `json:"parent_job_id"`
	JobStepID         string    `json:"job_step_id"`
	DeferredQty       float64   `json:"deferred_qty"`
	EarliestStartAt   time.Time `json:"earliest_start_at"`
	BlockingMaterials []string  `json:"blocking_materials"`
	PlanningStatus    string    `json:"planning_status"`
}

type MaterialShortageInfo struct {
	MaterialID               string                   `json:"material_id"`
	MaterialName             string                   `json:"material_name"`
	Unit                     string                   `json:"unit"`
	JobStepID                string                   `json:"job_step_id"`
	AllStepMaterialsFeasible bool                     `json:"all_step_materials_feasible"`
	ShortageStartAt          time.Time                `json:"shortage_start_at"`
	MaxDeficit               float64                  `json:"max_deficit"`
	CurrentStock             float64                  `json:"current_stock"`
	TotalReservedBefore      float64                  `json:"total_reserved_before"`
	FeasibleQty              float64                  `json:"feasible_qty"`
	AffectedJobIDs           []string                 `json:"affected_job_ids"`
	AffectedStepIDs          []string                 `json:"affected_step_ids"`
	Snapshot                 *InventorySnapshot       `json:"snapshot,omitempty"`
	PerMaterialResolutions   []ShortageResolutionOption `json:"per_material_resolutions"`
}

// BatchMaterialReplenishmentLine is one consolidated raw-material recommendation for an
// entire batch (batch-proposals / reschedule-all). It merges every proposal's
// reserve_material actions into one timeline so recommended_qty reflects combined demand,
// not a naive sum of per-job shortage cards.
type BatchMaterialReplenishmentLine struct {
	MaterialID              string    `json:"material_id"`
	MaterialName            string    `json:"material_name"`
	Unit                    string    `json:"unit,omitempty"`
	RecommendedQty          float64   `json:"recommended_qty"`
	SuggestedArriveAt       time.Time `json:"suggested_arrive_at"`
	EarliestPossibleArrival time.Time `json:"earliest_possible_arrival"`
	ShortageStartAt         time.Time `json:"shortage_start_at"`
	OptionType              string    `json:"option_type"`
	AffectedJobIDs          []string  `json:"affected_job_ids"`
	Rationale               string    `json:"rationale"`
}

// BatchScheduleProductionLine is one consolidated schedule_production recommendation for the
// whole batch (subproduct / FG planned inventory). Apply via apply-replenishment with
// option_type=schedule_production, same as per-proposal shortage_resolutions rows.
type BatchScheduleProductionLine struct {
	ProductID               string    `json:"product_id"`
	ProductName             string    `json:"product_name,omitempty"`
	RecommendedQty          float64   `json:"recommended_qty"`
	SuggestedArriveAt       time.Time `json:"suggested_arrive_at"`
	EarliestPossibleArrival time.Time `json:"earliest_possible_arrival"`
	OptionType              string    `json:"option_type"`
	AffectedJobIDs          []string  `json:"affected_job_ids"`
	Rationale               string    `json:"rationale"`
}

type ReplanConvergenceWarning struct {
	MaterialID    string  `json:"material_id"`
	DeficitBefore float64 `json:"deficit_before"`
	DeficitAfter  float64 `json:"deficit_after"`
	Attempts      int     `json:"attempts"`
	Message       string  `json:"message"`
}

type DependentJobPlan struct {
	PlanKey             string              `json:"plan_key"`
	ParentJobID         string              `json:"parent_job_id"`
	ConsumerJobStepID   string              `json:"consumer_job_step_id"`
	ProductID           string              `json:"product_id"`
	DependencyDepth     int                 `json:"dependency_depth"`
	RequiredQty         float64             `json:"required_qty"`
	PlannedQty          float64             `json:"planned_qty"`
	ShortageQty         float64             `json:"shortage_qty"`
	ExistingStock       float64             `json:"existing_stock"`
	FutureStockQty      float64             `json:"future_stock_qty"`
	FutureStockReadyAt  *time.Time          `json:"future_stock_ready_at,omitempty"`
	EstimatedCompletion *time.Time          `json:"estimated_completion,omitempty"`
	PlanningStatus      string              `json:"planning_status"`
	ReasonCode          string              `json:"reason_code,omitempty"`
	Reason              string              `json:"reason,omitempty"`
	Explanation         ProposalExplanation `json:"explanation"`
	ProposedSlots       []ProposedSlot      `json:"proposed_slots,omitempty"`
	GeneratedJobID      string              `json:"generated_job_id,omitempty"`
	GeneratedStepIDMap  map[string]string   `json:"generated_step_id_map,omitempty"`
	ReplenishmentSuggestion *ReplenishmentSuggestion `json:"replenishment_suggestion,omitempty"`
	ResolutionOptions       []ShortageResolutionOption `json:"resolution_options,omitempty"`
	PartialFeasibility      *PartialFeasibilityPlan `json:"partial_feasibility,omitempty"`
}

type InventoryAction struct {
	Sequence    int       `json:"sequence"`
	ActionType  string    `json:"action_type"`
	ResourceID  string    `json:"resource_id"`
	JobID       string    `json:"job_id"`
	JobStepID   string    `json:"job_step_id"`
	Quantity    float64   `json:"quantity"`
	EffectiveAt time.Time `json:"effective_at"`
	ReasonCode  string    `json:"reason_code,omitempty"`
	PlanKey     string    `json:"plan_key,omitempty"`
}

type CreatedDependencyLink struct {
	DependencyID string `json:"dependency_id"`
	ParentJobID  string `json:"parent_job_id"`
	ChildJobID   string `json:"child_job_id"`
	ProductID    string `json:"product_id"`
}

type SchedulingProposal struct {
	ProposalID           string             `json:"proposal_id,omitempty"`
	JobID                string             `json:"job_id"`
	ProductID            string             `json:"product_id"`
	Version              int                `json:"version,omitempty"`
	Status               string             `json:"status,omitempty"`
	Engine               string             `json:"engine,omitempty"`
	EngineVersion        string             `json:"engine_version,omitempty"`
	ObjectiveScore       float64            `json:"objective_score,omitempty"`
	FallbackReason       string             `json:"fallback_reason,omitempty"`
	SnapshotHash         string             `json:"snapshot_hash,omitempty"`
	RolloutState         string             `json:"rollout_state,omitempty"`
	ShadowEngine         string             `json:"shadow_engine,omitempty"`
	ShadowObjectiveScore float64            `json:"shadow_objective_score,omitempty"`
	GeneratedAt          time.Time          `json:"generated_at"`
	Feasible             bool               `json:"feasible"`
	EarliestStart        time.Time          `json:"earliest_start"`
	EstimatedCompletion  *time.Time         `json:"estimated_completion,omitempty"`
	Summary              []string           `json:"summary"`
	BlockedReasons       []string           `json:"blocked_reasons,omitempty"`
	ProposedSlots        []ProposedSlot     `json:"proposed_slots"`
	DependentJobs        []DependentJobPlan `json:"dependent_jobs,omitempty"`
	InventoryActions     []InventoryAction  `json:"inventory_actions,omitempty"`
	InventoryActionCount int                `json:"inventory_action_count,omitempty"`
	MaterialShortages    []MaterialShortageInfo `json:"material_shortages,omitempty"`
	ShortageResolutions  []ShortageResolutionOption `json:"shortage_resolutions,omitempty"`
	PartialFeasibility   *PartialFeasibilityPlan `json:"partial_feasibility,omitempty"`
	DeferredNodes        []DeferredPlanningNode `json:"deferred_nodes,omitempty"`
	ConvergenceWarnings  []ReplanConvergenceWarning `json:"convergence_warnings,omitempty"`
	GlobalScore          float64 `json:"global_score,omitempty"`

	// Alternatives are additional distinct schedules for the same job generated via
	// a heuristic portfolio; each alternative does not include nested alternatives.
	Alternatives []SchedulingProposal `json:"alternatives,omitempty"`

	// DeadlineStatus is set when proposal is part of a batch; nil for single-job endpoints.
	DeadlineStatus *DeadlineStatus `json:"deadline_status,omitempty"`
}

// DeadlineStatus describes whether a job will complete by its deadline.
type DeadlineStatus struct {
	Deadline      time.Time `json:"deadline"`       // job's deadline
	IsLate        bool      `json:"is_late"`        // estimated_completion > deadline
	TardinessMins int       `json:"tardiness_mins"` // minutes past deadline (0 if on time)
	LateBy        string    `json:"late_by"`        // human-readable: "2 days", "5 hours"
}

// VerifySlotInput is a slot for overlap verification
type VerifySlotInput struct {
	JobStepID      string    `json:"job_step_id"`
	MachineID      string    `json:"machine_id"`
	ScheduledStart time.Time `json:"scheduled_start"`
	ScheduledEnd   time.Time `json:"scheduled_end"`
}

// VerifyOverlapsInput is one proposal for overlap verification
type VerifyOverlapsInput struct {
	ProposalID    string            `json:"proposal_id"`
	JobID         string            `json:"job_id"`
	ProposedSlots []VerifySlotInput `json:"proposed_slots"`
}

// VerifyOverlapsResult is the overlap verification report
type VerifyOverlapsResult struct {
	Valid             bool             `json:"valid"` // true if no overlaps
	TotalSlots        int              `json:"total_slots"`
	OverlapCount      int              `json:"overlap_count"`
	Overlaps          []MachineOverlap `json:"overlaps"`
	Scope             string           `json:"scope,omitempty"` // proposals | applied
	CheckedJobIDs     []string         `json:"checked_job_ids,omitempty"`
	FailedProposalIDs []string         `json:"failed_proposal_ids,omitempty"`
	Partial           bool             `json:"partial,omitempty"`
}

// MachineOverlap describes two slots that overlap on the same machine
type MachineOverlap struct {
	MachineID    string    `json:"machine_id"`
	SlotA        SlotRef   `json:"slot_a"`
	SlotB        SlotRef   `json:"slot_b"`
	OverlapStart time.Time `json:"overlap_start"`
	OverlapEnd   time.Time `json:"overlap_end"`
}

// SlotRef references a slot for overlap reporting
type SlotRef struct {
	JobID          string    `json:"job_id"`
	ProposalID     string    `json:"proposal_id"`
	JobStepID      string    `json:"job_step_id"`
	ScheduledStart time.Time `json:"scheduled_start"`
	ScheduledEnd   time.Time `json:"scheduled_end"`
}

type AppliedProposalResult struct {
	ProposalID             string                  `json:"proposal_id,omitempty"`
	JobID                  string                  `json:"job_id"`
	AppliedAt              time.Time               `json:"applied_at"`
	AppliedSlotCount       int                     `json:"applied_slot_count"`
	CreatedSlots           []string                `json:"created_slots"`
	CreatedJobIDs          []string                `json:"created_job_ids,omitempty"`
	CreatedDependencyLinks []CreatedDependencyLink `json:"created_dependency_links,omitempty"`
	Message                string                  `json:"message"`
	IdempotencyKey         string                  `json:"idempotency_key,omitempty"`
	Proposal               *SchedulingProposal     `json:"proposal,omitempty"`
}

type AISchedulingAssist struct {
	JobID               string                     `json:"job_id"`
	Readiness           *SchedulingReadinessResult `json:"readiness,omitempty"`
	SolverPreview       *SolverPreview             `json:"solver_preview,omitempty"`
	EstimatedCompletion *CompletionEstimate        `json:"estimated_completion,omitempty"`
	DelayRisk           *HighRiskJobPrediction     `json:"delay_risk,omitempty"`
	SplitSuggestions    []SplitSuggestion          `json:"split_suggestions,omitempty"`
	Explanation         []string                   `json:"explanation"`
}

type AIPredictiveService struct {
	db              *gorm.DB
	jobRepo         *repository.JobRepository
	stepRepo        *repository.JobStepRepository
	slotRepo        *repository.JobSlotRepository
	proposalRepo    *repository.AIProposalRepository
	machineRepo     *repository.MachineRepository
	maintenanceRepo *repository.MaintenanceRepository
	settingsRepo    *repository.SystemSettingsRepository
	scheduling      *SchedulingService
	jobSlotService  *JobSlotService
	eventRepo       *repository.SchedulingEventRepository
	metrics         *AIMetrics
}

func NewAIPredictiveService(
	db *gorm.DB,
	jobRepo *repository.JobRepository,
	stepRepo *repository.JobStepRepository,
	slotRepo *repository.JobSlotRepository,
	proposalRepo *repository.AIProposalRepository,
	machineRepo *repository.MachineRepository,
	maintenanceRepo *repository.MaintenanceRepository,
	settingsRepo *repository.SystemSettingsRepository,
	scheduling *SchedulingService,
	jobSlotService *JobSlotService,
	eventRepo *repository.SchedulingEventRepository,
) *AIPredictiveService {
	return &AIPredictiveService{
		db:              db,
		jobRepo:         jobRepo,
		stepRepo:        stepRepo,
		slotRepo:        slotRepo,
		proposalRepo:    proposalRepo,
		machineRepo:     machineRepo,
		maintenanceRepo: maintenanceRepo,
		settingsRepo:    settingsRepo,
		scheduling:      scheduling,
		jobSlotService:  jobSlotService,
		eventRepo:       eventRepo,
		metrics:         NewAIMetrics(),
	}
}

func (s *AIPredictiveService) buildDelayRisk(job domain.Job) (*DelayRiskDetail, error) {
	// 1) ML-first (strict timeout), 2) heuristic fallback.
	if mlDetail, ok := s.buildDelayRiskFromML(job); ok {
		return mlDetail, nil
	}

	return s.buildDelayRiskHeuristic(job)
}

func (s *AIPredictiveService) buildDelayRiskHeuristic(job domain.Job) (*DelayRiskDetail, error) {
	readiness, _ := s.scheduling.CheckReadiness(job.ProductID, float64(job.QuantityTotal))
	estimate, _ := s.scheduling.EstimateJobEarliestCompletion(job.JobID)
	reasons := make([]string, 0, 4)
	score := 0.0
	issue := "Capacity pressure"
	delayMinutes := 0
	now := time.Now()

	if job.Status == domain.JobStatusPaused {
		score += 15
		issue = "Paused execution"
		reasons = append(reasons, "Job status is paused.")
	}
	if readiness != nil && !readiness.CanStartNow {
		score += 25
		issue = "Material or sub-product not ready"
		reasons = append(reasons, "Material readiness or sub-product readiness prevents immediate start.")
	}
	if estimate != nil && estimate.EstimatedCompletion.After(job.Deadline) {
		delayMinutes = int(estimate.EstimatedCompletion.Sub(job.Deadline).Minutes())
		score += 35
		issue = "Projected late completion"
		reasons = append(reasons, "Current heuristic completion estimate is later than the job deadline.")
	}
	if job.Deadline.Before(now) {
		score += 40
		issue = "Deadline already missed"
		delayMinutes = int(now.Sub(job.Deadline).Minutes())
		reasons = append(reasons, "The job deadline is already in the past.")
	}

	steps, _ := s.stepRepo.ListByJobID(job.JobID)
	firstMachine := firstMachineID(steps, s.slotRepo)
	if firstMachine != "" {
		maints, _ := s.maintenanceRepo.ListByMachineID(firstMachine)
		if len(maints) > 0 {
			score += 10
			reasons = append(reasons, "Assigned machine has maintenance history that may affect stability.")
		}
	}
	if len(reasons) == 0 {
		reasons = append(reasons, "No major scheduling risk drivers were detected with current heuristics.")
	}
	if score == 0 {
		score = 10
	}
	level := "Low"
	if score >= 60 {
		level = "High"
	} else if score >= 30 {
		level = "Medium"
	}

	detail := &DelayRiskDetail{
		JobID:        job.JobID,
		ProductID:    job.ProductID,
		RiskLevel:    level,
		RiskScore:    score,
		RiskSource:   "heuristic_fallback",
		Issue:        issue,
		DelayMinutes: delayMinutes,
		Deadline:     job.Deadline,
		Reasons:      reasons,
	}
	if readiness != nil {
		detail.EarliestReadyAt = readiness.EarliestReadyAt
	}
	if estimate != nil {
		completion := estimate.EstimatedCompletion
		detail.EstimatedCompletion = &completion
	}
	return detail, nil
}

func (s *AIPredictiveService) buildDelayRiskFromML(job domain.Job) (*DelayRiskDetail, bool) {
	if s.proposalRepo == nil {
		return nil, false
	}
	// Need snapshot vectors; use latest proposal snapshot.
	latest, err := s.proposalRepo.LatestByJobID(job.JobID)
	if err != nil || latest == nil || latest.SnapshotJSON == "" {
		return nil, false
	}
	var snap snapshotVectors
	if err := json.Unmarshal([]byte(latest.SnapshotJSON), &snap); err != nil {
		return nil, false
	}
	if len(snap.MachineIDs) == 0 || len(snap.QueueLengthsVector) != len(snap.MachineIDs) || len(snap.MachineUtilizationVector) != len(snap.MachineIDs) {
		return nil, false
	}

	readiness, _ := s.scheduling.CheckReadiness(job.ProductID, float64(job.QuantityTotal))
	estimate, _ := s.scheduling.EstimateJobEarliestCompletion(job.JobID)
	canStartNow := readiness != nil && readiness.CanStartNow
	req := &MLRiskRequest{
		JobID:       job.JobID,
		ProductID:   job.ProductID,
		JobPriority: job.Priority,
		MaterialShortageCount: func() int {
			if readiness == nil {
				return 0
			}
			c := 0
			for _, m := range readiness.Materials {
				if m.ShortageQty > 0 {
					c++
				}
			}
			return c
		}(),
		SubProductShortageCount: func() int {
			if readiness == nil {
				return 0
			}
			c := 0
			for _, sp := range readiness.SubProducts {
				if sp.ShortageQty > 0 {
					c++
				}
			}
			return c
		}(),
		CanStartNow: &canStartNow,
		Now:         time.Now().UTC().Format(time.RFC3339),
		Deadline:    job.Deadline.UTC().Format(time.RFC3339),
		EstimatedCompletion: func() string {
			if estimate == nil {
				return ""
			}
			return estimate.EstimatedCompletion.UTC().Format(time.RFC3339)
		}(),
		SnapshotMachineIDs:       snap.MachineIDs,
		QueueLengthsVector:       snap.QueueLengthsVector,
		MachineUtilizationVector: snap.MachineUtilizationVector,
	}
	featureCoverage := mlRiskRequestCoverage(req)

	client, err := NewMLInferenceClient(DefaultMLBaseURL(), 45*time.Millisecond)
	if err != nil {
		return nil, false
	}
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Millisecond)
	defer cancel()
	resp, latency, err := client.PredictDelayRisk(ctx, req)
	if err != nil || resp == nil {
		if s.metrics != nil {
			s.metrics.RecordMLFailure()
		}
		if err != nil {
			logger.L().Warn("ml_delay_risk_fallback",
				zap.String("job_id", job.JobID),
				zap.String("reason", "predict_failed"),
				zap.Error(err),
			)
		}
		return nil, false
	}
	if resp.FallbackRecommended || resp.ConfidenceScore < mlDelayRiskConfidenceThreshold {
		if s.metrics != nil {
			s.metrics.RecordMLLowConfidenceFallback(latency.Seconds()*1000, featureCoverage)
		}
		logger.L().Info("ml_delay_risk_fallback",
			zap.String("job_id", job.JobID),
			zap.String("reason", "low_confidence"),
			zap.Float64("confidence_score", resp.ConfidenceScore),
			zap.Bool("fallback_recommended", resp.FallbackRecommended),
			zap.String("model_version", resp.ModelVersion),
		)
		return nil, false
	}
	if s.metrics != nil {
		s.metrics.RecordMLSuccess(latency.Seconds()*1000, featureCoverage)
	}

	// Map ML outputs into DelayRiskDetail while keeping existing fields.
	level := "Low"
	if resp.DelaySeverity != "" {
		level = resp.DelaySeverity
	}
	detail := &DelayRiskDetail{
		JobID:              job.JobID,
		ProductID:          job.ProductID,
		RiskLevel:          level,
		RiskScore:          resp.ProbabilityOfDelay * 100.0,
		ProbabilityOfDelay: resp.ProbabilityOfDelay,
		DelaySeverity:      resp.DelaySeverity,
		PredictedDelayMins: resp.PredictedDelayMinutes,
		RiskSource:         "ml",
		Issue:              "ML risk prediction",
		DelayMinutes:       0,
		Deadline:           job.Deadline,
		Reasons:            append([]string{fmt.Sprintf("ML model %s", resp.ModelVersion)}, resp.FeatureSummary...),
	}
	if readiness != nil {
		detail.EarliestReadyAt = readiness.EarliestReadyAt
	}
	if estimate != nil {
		completion := estimate.EstimatedCompletion
		detail.EstimatedCompletion = &completion
	}
	return detail, true
}

func mlRiskRequestCoverage(req *MLRiskRequest) float64 {
	if req == nil {
		return 0
	}
	signals := []bool{
		strings.TrimSpace(req.JobPriority) != "",
		req.CanStartNow != nil,
		strings.TrimSpace(req.Deadline) != "",
		strings.TrimSpace(req.EstimatedCompletion) != "",
		len(req.QueueLengthsVector) > 0,
		len(req.MachineUtilizationVector) > 0,
		req.MaterialShortageCount != 0,
		req.SubProductShortageCount != 0,
	}
	count := 0
	for _, signal := range signals {
		if signal {
			count++
		}
	}
	return float64(count) / float64(len(signals))
}

func (s *AIPredictiveService) GetDelayRisk(jobID string) (*DelayRiskDetail, error) {
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, err
	}
	return s.buildDelayRisk(*job)
}

func (s *AIPredictiveService) RankMachinesForJobStep(jobStepID string, start, end time.Time) (*MachineRankingResult, error) {
	jobStep, processStep, err := s.scheduling.resolveStepContext(jobStepID)
	if err != nil {
		return nil, err
	}
	if jobStep == nil {
		return nil, fmt.Errorf("job_step_id is required")
	}
	if !end.After(start) {
		end = start.Add(8 * time.Hour)
	}
	candidates, err := s.scheduling.CandidateMachinesForStep(jobStepID, start, end)
	if err != nil {
		return nil, err
	}
	result := &MachineRankingResult{
		JobStepID:   jobStepID,
		StepID:      processStep.StepID,
		StepName:    processStep.StepName,
		WindowStart: start,
		WindowEnd:   end,
		Candidates:  make([]RankedMachineCandidate, 0, len(candidates)),
	}
	for _, candidate := range candidates {
		score := candidate.EfficiencyFactor * 35
		explanation := make([]string, 0, 4)
		if candidate.Available {
			score += 40
			explanation = append(explanation, "Machine is currently schedulable in the requested window.")
		} else {
			waitHours := candidate.AvailableFrom.Sub(start).Hours()
			score -= waitHours * 6
			explanation = append(explanation, "Machine is not immediately schedulable and requires waiting for capacity or constraints to clear.")
		}
		if candidate.CapacityPerHour > 0 {
			score += float64(candidate.CapacityPerHour) / 4
			explanation = append(explanation, fmt.Sprintf("Rated capacity is %d units/hour.", candidate.CapacityPerHour))
		}
		duration := estimatedStepDuration(*processStep, []CandidateMachine{candidate}, float64(jobStep.QuantityTarget))
		explanation = append(explanation, fmt.Sprintf("Estimated single-machine duration is %d minutes for the current target quantity.", int(duration.Minutes())))
		if len(candidate.Reasons) > 0 {
			score -= float64(len(candidate.Reasons) * 5)
		}
		result.Candidates = append(result.Candidates, RankedMachineCandidate{
			MachineID:             candidate.MachineID,
			MachineName:           candidate.MachineName,
			MachineType:           candidate.MachineType,
			Available:             candidate.Available,
			AvailableFrom:         candidate.AvailableFrom,
			EfficiencyFactor:      candidate.EfficiencyFactor,
			CapacityPerHour:       candidate.CapacityPerHour,
			EstimatedDurationMins: int(duration.Minutes()),
			Score:                 mathRound(score, 2),
			Reasons:               candidate.Reasons,
			Explanation:           explanation,
		})
	}
	sort.Slice(result.Candidates, func(i, j int) bool {
		if result.Candidates[i].Score == result.Candidates[j].Score {
			return result.Candidates[i].MachineID < result.Candidates[j].MachineID
		}
		return result.Candidates[i].Score > result.Candidates[j].Score
	})
	for i := range result.Candidates {
		result.Candidates[i].Rank = i + 1
	}
	return result, nil
}

func (s *AIPredictiveService) ForecastBottlenecks(daysAhead int) (*BottleneckForecastResult, error) {
	if daysAhead <= 0 {
		daysAhead = 7
	}
	machines, err := s.machineRepo.ListAll()
	if err != nil {
		return nil, err
	}
	now := time.Now()
	cutoff := now.AddDate(0, 0, daysAhead)
	result := &BottleneckForecastResult{
		DaysAhead:   daysAhead,
		GeneratedAt: now.UTC(),
		Entries:     make([]BottleneckForecastEntry, 0, len(machines)),
	}
	for _, machine := range machines {
		slots, _ := s.slotRepo.ListByMachineID(machine.MachineID)
		upcomingSlots := 0
		scheduledMinutes := 0
		reasons := make([]string, 0, 4)
		for _, slot := range slots {
			if slot.Status == domain.SlotStatusCancelled {
				continue
			}
			if slot.ScheduledEnd.Before(now) || slot.ScheduledStart.After(cutoff) {
				continue
			}
			upcomingSlots++
			scheduledMinutes += int(slot.ScheduledEnd.Sub(slot.ScheduledStart).Minutes())
		}
		score := machine.UtilizationRate*40 + float64(upcomingSlots*8)
		if scheduledMinutes > 0 {
			score += float64(scheduledMinutes) / 30
		}
		if machine.Status == domain.MachineStatusMaintenance || machine.Status == domain.MachineStatusOffline {
			score += 20
			reasons = append(reasons, "Machine is already unavailable or under maintenance.")
		}
		maints, _ := s.maintenanceRepo.ListByMachineID(machine.MachineID)
		for _, mt := range maints {
			if mt.StartTime.After(now) && mt.StartTime.Before(cutoff) {
				score += 10
				reasons = append(reasons, "Maintenance is scheduled inside the forecast horizon.")
				break
			}
		}
		if machine.UtilizationRate >= 0.8 {
			reasons = append(reasons, "Current utilization rate is high.")
		}
		if upcomingSlots >= 3 {
			reasons = append(reasons, "Multiple upcoming slots are already assigned to this machine.")
		}
		if len(reasons) == 0 {
			reasons = append(reasons, "No significant bottleneck signals detected in the forecast window.")
		}
		entry := BottleneckForecastEntry{
			MachineID:        machine.MachineID,
			MachineName:      machine.MachineName,
			MachineType:      machine.MachineType,
			Status:           machine.Status,
			UpcomingSlots:    upcomingSlots,
			ScheduledMinutes: scheduledMinutes,
			UtilizationRate:  machine.UtilizationRate,
			LoadScore:        mathRound(score, 2),
			AtRisk:           score >= 60,
			Reasons:          reasons,
		}
		result.Entries = append(result.Entries, entry)
	}
	sort.Slice(result.Entries, func(i, j int) bool {
		if result.Entries[i].LoadScore == result.Entries[j].LoadScore {
			return result.Entries[i].MachineID < result.Entries[j].MachineID
		}
		return result.Entries[i].LoadScore > result.Entries[j].LoadScore
	})
	return result, nil
}

func (s *AIPredictiveService) ExplainJob(jobID string) (*SchedulingExplanation, error) {
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, err
	}
	delayRisk, _ := s.GetDelayRisk(jobID)
	preview, _ := s.scheduling.BuildSolverPreview(jobID)
	keyPoints := make([]string, 0, 6)
	recommended := make([]string, 0, 6)
	summary := "Job is currently feasible under the present heuristic AI rules."

	if delayRisk != nil {
		keyPoints = append(keyPoints, delayRisk.Reasons...)
		if delayRisk.RiskLevel == "High" {
			summary = "Job has high schedule risk and should be reviewed before execution."
			recommended = append(recommended, "Review readiness and due-date pressure immediately.")
		} else if delayRisk.RiskLevel == "Medium" {
			summary = "Job has medium schedule risk and should be monitored closely."
			recommended = append(recommended, "Monitor machine allocation and material readiness before release.")
		}
	}
	if preview != nil {
		for _, step := range preview.Steps {
			if len(step.CandidateMachines) == 0 {
				keyPoints = append(keyPoints, fmt.Sprintf("Step %s currently has no candidate machines.", step.StepName))
				recommended = append(recommended, fmt.Sprintf("Add capability coverage or alternative routing for step %s.", step.StepName))
				continue
			}
			best := step.CandidateMachines[0]
			keyPoints = append(keyPoints, fmt.Sprintf("Best current machine candidate for step %s is %s.", step.StepName, best.MachineName))
		}
	}
	steps, _ := s.stepRepo.ListByJobID(jobID)
	for _, step := range steps {
		suggestion, err := s.SuggestSplit(step.JobStepID)
		if err == nil && suggestion.IsParallel {
			recommended = append(recommended, fmt.Sprintf("Consider parallel split for step %s across %d machines.", step.JobStepID, suggestion.RecommendedSplits))
		}
	}
	if len(recommended) == 0 {
		recommended = append(recommended, "Keep the current schedule under observation and rerun AI assist before dispatch.")
	}
	return &SchedulingExplanation{
		JobID:              job.JobID,
		Summary:            summary,
		KeyPoints:          dedupeStrings(keyPoints),
		RecommendedActions: dedupeStrings(recommended),
		GeneratedAt:        time.Now().UTC(),
	}, nil
}

func (s *AIPredictiveService) ListHighRiskJobs(limit int) ([]HighRiskJobPrediction, error) {
	jobs, err := s.jobRepo.ListAll()
	if err != nil {
		return nil, err
	}
	if len(jobs) == 0 {
		return []HighRiskJobPrediction{
			{JobID: "NO-JOBS-001", MachineName: "Unassigned", Issue: "No production history yet", RiskLevel: "Low", RiskScore: 10},
			{JobID: "NO-JOBS-002", MachineName: "Unassigned", Issue: "Add more scheduling history to improve predictions", RiskLevel: "Low", RiskScore: 8},
		}, nil
	}
	result := make([]HighRiskJobPrediction, 0, len(jobs))
	for _, job := range jobs {
		detail, err := s.buildDelayRisk(job)
		if err != nil {
			return nil, err
		}
		steps, _ := s.stepRepo.ListByJobID(job.JobID)
		machineName := "Unassigned"
		if machineID := firstMachineID(steps, s.slotRepo); machineID != "" {
			if machine, err := s.machineRepo.GetByID(machineID); err == nil {
				machineName = machine.MachineName
			}
		}
		result = append(result, HighRiskJobPrediction{
			JobID:        job.JobID,
			MachineName:  machineName,
			Issue:        detail.Issue,
			RiskLevel:    detail.RiskLevel,
			RiskScore:    detail.RiskScore,
			DelayMinutes: detail.DelayMinutes,
		})
	}
	sort.Slice(result, func(i, j int) bool { return result[i].RiskScore > result[j].RiskScore })
	if limit > 0 && len(result) > limit {
		result = result[:limit]
	}
	return result, nil
}

func (s *AIPredictiveService) Recommendations() ([]AIRecommendation, error) {
	risks, err := s.ListHighRiskJobs(3)
	if err != nil {
		return nil, err
	}
	recs := make([]AIRecommendation, 0)
	for _, risk := range risks {
		if risk.RiskLevel == "High" {
			recs = append(recs, AIRecommendation{
				Icon:     "priority_high",
				Title:    fmt.Sprintf("Review %s on %s: %s.", risk.JobID, risk.MachineName, risk.Issue),
				Action:   "Open Schedule",
				Severity: "high",
			})
		}
	}
	maintenanceDue, _ := s.machineRepo.ListDueForMaintenance(7)
	if len(maintenanceDue) > 0 {
		recs = append(recs, AIRecommendation{
			Icon:     "auto_fix_high",
			Title:    fmt.Sprintf("%d machine(s) are due for maintenance within 7 days.", len(maintenanceDue)),
			Action:   "Review Maintenance",
			Severity: "medium",
		})
	}
	if len(recs) == 0 {
		recs = append(recs, AIRecommendation{
			Icon:     "insights",
			Title:    "Current schedule is stable. Monitor readiness and due-date drift.",
			Action:   "View Solver Preview",
			Severity: "low",
		})
	}
	return recs, nil
}

func (s *AIPredictiveService) Forecast(forecastType string) (*ForecastSeries, error) {
	if forecastType == "" {
		forecastType = "delays"
	}
	jobs, err := s.jobRepo.ListAll()
	if err != nil {
		return nil, err
	}
	points := make([]ForecastPoint, 0, 7)
	now := time.Now().UTC()
	for i := 0; i < 7; i++ {
		day := now.AddDate(0, 0, i)
		label := day.Format("Mon")
		value := 0.0
		for _, job := range jobs {
			if job.Deadline.YearDay() != day.YearDay() || job.Deadline.Year() != day.Year() {
				continue
			}
			if forecastType == "failures" {
				value += 1
				continue
			}
			estimate, _ := s.scheduling.EstimateJobEarliestCompletion(job.JobID)
			if estimate != nil && estimate.EstimatedCompletion.After(job.Deadline) {
				value += 1
			}
		}
		points = append(points, ForecastPoint{Label: label, Value: value})
	}
	return &ForecastSeries{Type: forecastType, Data: points}, nil
}

func (s *AIPredictiveService) Confidence() (*ConfidenceSummary, error) {
	jobs, err := s.jobRepo.ListAll()
	if err != nil {
		return nil, err
	}
	if len(jobs) == 0 {
		return &ConfidenceSummary{ConfidencePct: 0, Model: "HybridBaseline-v1", LastTrained: ""}, nil
	}
	withSteps := 0
	withSlots := 0
	withReadyData := 0
	for _, job := range jobs {
		steps, _ := s.stepRepo.ListByJobID(job.JobID)
		if len(steps) > 0 {
			withSteps++
		}
		hasSlots := false
		for _, step := range steps {
			slots, _ := s.slotRepo.ListByJobStepID(step.JobStepID)
			if len(slots) > 0 {
				hasSlots = true
				break
			}
		}
		if hasSlots {
			withSlots++
		}
		readiness, _ := s.scheduling.CheckReadiness(job.ProductID, float64(job.QuantityTotal))
		if readiness != nil {
			withReadyData++
		}
	}
	confidence := (float64(withSteps)/float64(len(jobs))*35 +
		float64(withSlots)/float64(len(jobs))*40 +
		float64(withReadyData)/float64(len(jobs))*25)
	return &ConfidenceSummary{
		ConfidencePct: mathRound(confidence, 1),
		Model:         "HybridBaseline-v1",
		LastTrained:   time.Now().UTC().Format(time.RFC3339),
	}, nil
}

func (s *AIPredictiveService) SuggestSplit(jobStepID string) (*SplitSuggestion, error) {
	jobStep, processStep, err := s.scheduling.resolveStepContext(jobStepID)
	if err != nil {
		return nil, err
	}
	if jobStep == nil {
		return nil, fmt.Errorf("job_step_id is required")
	}
	candidates, err := s.scheduling.CandidateMachinesForStep(jobStepID, time.Now(), time.Now().Add(8*time.Hour))
	if err != nil {
		return nil, err
	}
	available := 0
	for _, candidate := range candidates {
		if candidate.Available {
			available++
		}
	}
	if !processStep.AllowParallelExecution || processStep.MaxParallelMachines <= 1 || available <= 1 {
		return &SplitSuggestion{
			JobStepID:          jobStepID,
			RecommendedSplits:  1,
			AllocationPercents: []float64{100},
			IsParallel:         false,
			Reason:             "Step should remain on a single active slot under current capability and policy constraints.",
		}, nil
	}
	maxSplits := processStep.MaxParallelMachines
	if available < maxSplits {
		maxSplits = available
	}
	if processStep.MinSplitQty > 0 {
		qtyBound := jobStep.QuantityTarget / processStep.MinSplitQty
		if qtyBound > 0 && qtyBound < maxSplits {
			maxSplits = qtyBound
		}
	}
	if maxSplits <= 1 {
		maxSplits = 1
	}
	allocations := make([]float64, 0, maxSplits)
	base := 100.0 / float64(maxSplits)
	for i := 0; i < maxSplits; i++ {
		allocations = append(allocations, mathRound(base, 2))
	}
	return &SplitSuggestion{
		JobStepID:          jobStepID,
		RecommendedSplits:  maxSplits,
		AllocationPercents: allocations,
		IsParallel:         maxSplits > 1,
		Reason:             "Parallel split is recommended because the process step allows it and multiple feasible machines are available.",
	}, nil
}

func (s *AIPredictiveService) BuildAssist(jobID string) (*AISchedulingAssist, error) {
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, err
	}
	readiness, _ := s.scheduling.CheckReadiness(job.ProductID, float64(job.QuantityTotal))
	preview, _ := s.scheduling.BuildSolverPreview(jobID)
	estimate, _ := s.scheduling.EstimateJobEarliestCompletion(jobID)
	risks, _ := s.ListHighRiskJobs(0)
	var currentRisk *HighRiskJobPrediction
	for _, risk := range risks {
		if risk.JobID == jobID {
			riskCopy := risk
			currentRisk = &riskCopy
			break
		}
	}
	steps, _ := s.stepRepo.ListByJobID(jobID)
	suggestions := make([]SplitSuggestion, 0, len(steps))
	for _, step := range steps {
		suggestion, err := s.SuggestSplit(step.JobStepID)
		if err == nil {
			suggestions = append(suggestions, *suggestion)
		}
	}
	explanation := []string{
		"Hard feasibility still comes from backend readiness and slot validation rules.",
		"Machine ranking is generated from current availability, capability, and efficiency data.",
		"Split suggestions are baseline recommendations and should be validated by the planner before execution.",
	}
	return &AISchedulingAssist{
		JobID:               jobID,
		Readiness:           readiness,
		SolverPreview:       preview,
		EstimatedCompletion: estimate,
		DelayRisk:           currentRisk,
		SplitSuggestions:    suggestions,
		Explanation:         explanation,
	}, nil
}

// GetLatestProposalIDForJob returns the proposal_id of the latest draft or approved proposal for the job.
// Used when the user says "Apply proposal for job JOB-X" so the backend can resolve job -> proposal_id.
func (s *AIPredictiveService) GetLatestProposalIDForJob(jobID string) (string, error) {
	if s.proposalRepo == nil {
		return "", nil
	}
	p, err := s.proposalRepo.LatestByJobIDWithStatuses(jobID, []string{domain.AIProposalStatusApproved, domain.AIProposalStatusDraft})
	if err != nil || p == nil {
		return "", err
	}
	return p.ProposalID, nil
}

// VerifyOverlaps checks if proposed slots overlap on the same machine. Pass either
// proposalIDs (to fetch from DB) or proposals (inline data, e.g. from batch-proposals).
func (s *AIPredictiveService) VerifyOverlaps(proposalIDs []string, proposals []VerifyOverlapsInput) (*VerifyOverlapsResult, error) {
	var inputs []VerifyOverlapsInput
	var failedProposalIDs []string
	if len(proposals) > 0 {
		inputs = proposals
	} else {
		for _, id := range proposalIDs {
			record, err := s.proposalRepo.GetByID(id)
			if err != nil {
				failedProposalIDs = append(failedProposalIDs, id)
				continue
			}
			var p SchedulingProposal
			if err := json.Unmarshal([]byte(record.ProposalJSON), &p); err != nil {
				failedProposalIDs = append(failedProposalIDs, id)
				continue
			}
			slots := make([]VerifySlotInput, 0, len(p.ProposedSlots))
			for _, ps := range p.ProposedSlots {
				slots = append(slots, VerifySlotInput{
					JobStepID:      ps.JobStepID,
					MachineID:      ps.MachineID,
					ScheduledStart: ps.ScheduledStart,
					ScheduledEnd:   ps.ScheduledEnd,
				})
			}
			inputs = append(inputs, VerifyOverlapsInput{
				ProposalID:    p.ProposalID,
				JobID:         p.JobID,
				ProposedSlots: slots,
			})
		}
		if len(failedProposalIDs) > 0 {
			return nil, newSchedulingActionError(400, "verify-overlaps could not load proposal_ids: "+strings.Join(failedProposalIDs, ", "))
		}
	}
	type slotInfo struct {
		jobID, proposalID, jobStepID, machineID string
		start, end                              time.Time
	}
	var allSlots []slotInfo
	for _, inp := range inputs {
		for _, ps := range inp.ProposedSlots {
			if ps.MachineID == "" {
				continue
			}
			allSlots = append(allSlots, slotInfo{
				jobID:      inp.JobID,
				proposalID: inp.ProposalID,
				jobStepID:  ps.JobStepID,
				machineID:  ps.MachineID,
				start:      ps.ScheduledStart,
				end:        ps.ScheduledEnd,
			})
		}
	}
	byMachine := make(map[string][]slotInfo)
	for _, s := range allSlots {
		byMachine[s.machineID] = append(byMachine[s.machineID], s)
	}
	var overlaps []MachineOverlap
	for _, slots := range byMachine {
		for i := 0; i < len(slots); i++ {
			for j := i + 1; j < len(slots); j++ {
				a, b := slots[i], slots[j]
				if a.start.Before(b.end) && a.end.After(b.start) {
					oStart := a.start
					if b.start.After(oStart) {
						oStart = b.start
					}
					oEnd := a.end
					if b.end.Before(oEnd) {
						oEnd = b.end
					}
					overlaps = append(overlaps, MachineOverlap{
						MachineID:    a.machineID,
						OverlapStart: oStart,
						OverlapEnd:   oEnd,
						SlotA: SlotRef{
							JobID:          a.jobID,
							ProposalID:     a.proposalID,
							JobStepID:      a.jobStepID,
							ScheduledStart: a.start,
							ScheduledEnd:   a.end,
						},
						SlotB: SlotRef{
							JobID:          b.jobID,
							ProposalID:     b.proposalID,
							JobStepID:      b.jobStepID,
							ScheduledStart: b.start,
							ScheduledEnd:   b.end,
						},
					})
				}
			}
		}
	}
	return &VerifyOverlapsResult{
		Valid:             len(overlaps) == 0,
		TotalSlots:        len(allSlots),
		OverlapCount:      len(overlaps),
		Overlaps:          overlaps,
		Scope:             "proposals",
		FailedProposalIDs: failedProposalIDs,
		Partial:           len(failedProposalIDs) > 0,
	}, nil
}

// VerifyOverlapsFromAppliedSlots verifies overlaps in job_step_schedule_slots (status planned/running).
// jobIDs is optional; if nil or empty, checks all jobs with active slots.
func (s *AIPredictiveService) VerifyOverlapsFromAppliedSlots(jobIDs []string) (*VerifyOverlapsResult, error) {
	rows, err := s.slotRepo.ListActiveByJobIDs(jobIDs)
	if err != nil {
		return nil, err
	}
	type slotInfo struct {
		jobID, proposalID, jobStepID, machineID string
		start, end                              time.Time
	}
	var allSlots []slotInfo
	for _, r := range rows {
		if r.MachineID == "" {
			continue
		}
		allSlots = append(allSlots, slotInfo{
			jobID:      r.JobID,
			proposalID: r.ProposalID,
			jobStepID:  r.JobStepID,
			machineID:  r.MachineID,
			start:      r.ScheduledStart,
			end:        r.ScheduledEnd,
		})
	}
	byMachine := make(map[string][]slotInfo)
	for _, s := range allSlots {
		byMachine[s.machineID] = append(byMachine[s.machineID], s)
	}
	var overlaps []MachineOverlap
	for _, slots := range byMachine {
		for i := 0; i < len(slots); i++ {
			for j := i + 1; j < len(slots); j++ {
				a, b := slots[i], slots[j]
				if a.start.Before(b.end) && a.end.After(b.start) {
					oStart := a.start
					if b.start.After(oStart) {
						oStart = b.start
					}
					oEnd := a.end
					if b.end.Before(oEnd) {
						oEnd = b.end
					}
					overlaps = append(overlaps, MachineOverlap{
						MachineID:    a.machineID,
						OverlapStart: oStart,
						OverlapEnd:   oEnd,
						SlotA: SlotRef{
							JobID:          a.jobID,
							ProposalID:     a.proposalID,
							JobStepID:      a.jobStepID,
							ScheduledStart: a.start,
							ScheduledEnd:   a.end,
						},
						SlotB: SlotRef{
							JobID:          b.jobID,
							ProposalID:     b.proposalID,
							JobStepID:      b.jobStepID,
							ScheduledStart: b.start,
							ScheduledEnd:   b.end,
						},
					})
				}
			}
		}
	}
	return &VerifyOverlapsResult{
		Valid:         len(overlaps) == 0,
		TotalSlots:    len(allSlots),
		OverlapCount:  len(overlaps),
		Overlaps:      overlaps,
		Scope:         "applied",
		CheckedJobIDs: jobIDs,
	}, nil
}

func firstMachineID(steps []domain.JobSteps, slotRepo *repository.JobSlotRepository) string {
	for _, step := range steps {
		slots, _ := slotRepo.ListByJobStepID(step.JobStepID)
		if len(slots) > 0 {
			return slots[0].MachineID
		}
	}
	return ""
}

func mathRound(v float64, decimals int) float64 {
	pow := 1.0
	for i := 0; i < decimals; i++ {
		pow *= 10
	}
	return float64(int(v*pow+0.5)) / pow
}

func dedupeStrings(items []string) []string {
	seen := make(map[string]bool, len(items))
	out := make([]string, 0, len(items))
	for _, item := range items {
		if item == "" || seen[item] {
			continue
		}
		seen[item] = true
		out = append(out, item)
	}
	return out
}

func allocateSplitQuantities(total int, percentages []float64, count int, minBatchSize int) []int {
	if count <= 0 {
		return nil
	}
	if len(percentages) < count {
		percentages = append(percentages, make([]float64, count-len(percentages))...)
	}
	allocations := make([]int, count)
	assigned := 0
	for i := 0; i < count; i++ {
		if i == count-1 {
			allocations[i] = total - assigned
			break
		}
		pct := percentages[i]
		if pct <= 0 {
			pct = 100 / float64(count)
		}
		qty := int(float64(total) * pct / 100)
		if qty < 0 {
			qty = 0
		}
		if minBatchSize > 0 && qty > 0 && qty < minBatchSize {
			qty = minBatchSize
			if qty > total-assigned {
				qty = total - assigned
			}
		}
		allocations[i] = qty
		assigned += qty
	}
	if allocations[count-1] < 0 {
		allocations[count-1] = 0
	}
	return allocations
}

// EmitSchedulingEvent creates a scheduling event (machine_down, job_delay, urgent_insert).
// If AI_AUTO_RESCHEDULE_ON_EVENT is true, triggers RescheduleAll.
func (s *AIPredictiveService) EmitSchedulingEvent(eventType, payload string) error {
	if s.eventRepo == nil {
		return nil
	}
	evt := &domain.SchedulingEvent{
		ID:        id.NewPrefixed("EVT-"),
		Type:      eventType,
		Payload:   payload,
		CreatedAt: time.Now().UTC(),
	}
	if err := s.eventRepo.Create(evt); err != nil {
		return err
	}
	if featureflags.AutoRescheduleOnEvent() {
		// Deadline is applied inside ScheduleJobSet from resolved job count (AdaptiveBatchTimeoutMs).
		_, _, _ = s.RescheduleAll(context.Background(), featureflags.BatchOrderBy(), "", false)
	}
	return nil
}
