package schedulereval

import (
	"time"

	"emas/internal/service"
)

const (
	EndpointBatchProposals = "batch-proposals"
	EndpointRescheduleAll  = "reschedule-all"
)

const (
	SeverityError   = "error"
	SeverityWarning = "warning"
)

// RunMetadata identifies one scheduler evaluation run. Keep these fields stable:
// reports and baselines are meant to be diffed across scheduler versions.
type RunMetadata struct {
	GitSHA           string    `json:"git_sha,omitempty"`
	SchedulerProfile string    `json:"scheduler_profile,omitempty"`
	SchedulerEngine  string    `json:"scheduler_engine,omitempty"`
	SchedulerVersion string    `json:"scheduler_version,omitempty"`
	ScenarioID       string    `json:"scenario_id"`
	SeedFingerprint  string    `json:"seed_fingerprint,omitempty"`
	Endpoint         string    `json:"endpoint"`
	OrderBy          string    `json:"order_by,omitempty"`
	DryRun           bool      `json:"dry_run"`
	Timestamp        time.Time `json:"timestamp"`
}

type EndpointResult struct {
	Metadata  RunMetadata
	Proposals []*service.SchedulingProposal
	Summary   *service.BatchProposalSummary
	Runtime   time.Duration
	Partial   bool
}

type Finding struct {
	Code       string `json:"code"`
	Severity   string `json:"severity"`
	Message    string `json:"message"`
	JobID      string `json:"job_id,omitempty"`
	ProposalID string `json:"proposal_id,omitempty"`
	MachineID  string `json:"machine_id,omitempty"`
	StepID     string `json:"step_id,omitempty"`
	MaterialID string `json:"material_id,omitempty"`
}

type CorrectnessMetrics struct {
	MachineOverlapCount          int `json:"machine_overlap_count"`
	InvalidTimeRangeCount        int `json:"invalid_time_range_count"`
	MissingSlotsCount            int `json:"missing_slots_count"`
	DuplicateSlotCount           int `json:"duplicate_slot_count"`
	StepOrderViolationCount      int `json:"step_order_violation_count"`
	IncompatibleResourceUseCount int `json:"incompatible_resource_use_count"`
}

type MaterialMetrics struct {
	MaterialShortageProposalCount  int      `json:"material_shortage_proposal_count"`
	MaterialShortageCount          int      `json:"material_shortage_count"`
	AggregateReplenishmentCount    int      `json:"aggregate_replenishment_count"`
	AggregateMaterialIDs           []string `json:"aggregate_material_ids,omitempty"`
	AggregateAccelerationCount     int      `json:"aggregate_acceleration_count"`
	AggregateAccelerationIDs       []string `json:"aggregate_acceleration_ids,omitempty"`
	UnaccountedNegativeLedgerCount int      `json:"unaccounted_negative_ledger_count"`
	FutureArrivalViolationCount    int      `json:"future_arrival_violation_count"`
	ChildMaterialEvidenceCount     int      `json:"child_material_evidence_count"`
}

type FeasibilityMetrics struct {
	FeasibleJobs                      int      `json:"feasible_jobs"`
	InfeasibleJobs                    int      `json:"infeasible_jobs"`
	FeasibleWithoutSlots              int      `json:"feasible_without_slots"`
	InfeasibleWithoutReason           int      `json:"infeasible_without_reason"`
	InfeasibleWithoutShortageEvidence int      `json:"infeasible_without_shortage_evidence"`
	SilentExcludedJobs                int      `json:"silent_excluded_jobs"`
	BlockedJobIDs                     []string `json:"blocked_job_ids,omitempty"`
}

type QualityMetrics struct {
	OnTimeCount           int             `json:"on_time_count"`
	LateCount             int             `json:"late_count"`
	TotalTardinessMins    int             `json:"total_tardiness_mins"`
	WeightedTardinessMins int             `json:"weighted_tardiness_mins"`
	MaxTardinessMins      int             `json:"max_tardiness_mins"`
	MakespanMins          int             `json:"makespan_mins"`
	MachineUtilizationPct float64         `json:"machine_utilization_pct"`
	WaitTimeMins          int             `json:"wait_time_mins"`
	SetupSwitches         int             `json:"setup_switches"`
	TopLateJobs           []LateJobMetric `json:"top_late_jobs,omitempty"`
}

type LateJobMetric struct {
	JobID               string     `json:"job_id"`
	ProductID           string     `json:"product_id,omitempty"`
	TardinessMins       int        `json:"tardiness_mins"`
	Deadline            *time.Time `json:"deadline,omitempty"`
	EstimatedCompletion *time.Time `json:"estimated_completion,omitempty"`
}

type PerformanceMetrics struct {
	RuntimeMS     int64   `json:"runtime_ms"`
	JobsPerSecond float64 `json:"jobs_per_second"`
	ProposalCount int     `json:"proposal_count"`
	BlockedCount  int     `json:"blocked_count"`
}

type StabilityMetrics struct {
	ScheduleHash string             `json:"schedule_hash"`
	BaselineHash string             `json:"baseline_hash,omitempty"`
	MetricDeltas map[string]float64 `json:"metric_deltas,omitempty"`
}

type ScoreBreakdown struct {
	HardGatePassed   bool    `json:"hard_gate_passed"`
	CorrectnessScore float64 `json:"correctness_score"`
	QualityScore     float64 `json:"quality_score"`
	PerformanceScore float64 `json:"performance_score"`
	OverallScore     float64 `json:"overall_score"`
}

type Scorecard struct {
	SchemaVersion int                `json:"schema_version"`
	Metadata      RunMetadata        `json:"metadata"`
	Score         ScoreBreakdown     `json:"score"`
	Correctness   CorrectnessMetrics `json:"correctness"`
	Material      MaterialMetrics    `json:"material_validity"`
	Feasibility   FeasibilityMetrics `json:"feasibility_semantics"`
	Quality       QualityMetrics     `json:"schedule_quality"`
	Performance   PerformanceMetrics `json:"performance"`
	Stability     StabilityMetrics   `json:"stability"`
	Failures      []Finding          `json:"failures,omitempty"`
	Warnings      []Finding          `json:"warnings,omitempty"`
}

func (s Scorecard) HardFailureCount() int {
	return len(s.Failures)
}
