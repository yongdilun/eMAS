package service

import (
	"context"
	"crypto/sha256"
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/featureflags"
	"emas/pkg/id"
	"emas/pkg/logger"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"go.uber.org/zap"
	"gorm.io/gorm"
)

type SchedulingActionError struct {
	StatusCode int
	Message    string
}

func (e *SchedulingActionError) Error() string {
	return e.Message
}

func newSchedulingActionError(statusCode int, message string) error {
	return &SchedulingActionError{StatusCode: statusCode, Message: message}
}

type proposalSnapshot struct {
	Job              proposalSnapshotJob               `json:"job"`
	Preview          proposalSnapshotPreview           `json:"preview"`
	ExistingSlots    []proposalSnapshotSlot            `json:"existing_slots"`
	Inventory        proposalSnapshotInventory         `json:"inventory"`
	DependentJobs    []proposalSnapshotDependentJob    `json:"dependent_jobs,omitempty"`
	InventoryActions []proposalSnapshotInventoryAction `json:"inventory_actions,omitempty"`

	// MachineIDs defines the fixed ordering for all vector features.
	MachineIDs []string `json:"machine_ids"`

	QueueLengthsVector       []int     `json:"queue_lengths_vector"`
	MachineUtilizationVector []float64 `json:"machine_utilization_vector"`
}

type proposalSnapshotInventory struct {
	Materials            []proposalSnapshotMaterialState    `json:"materials,omitempty"`
	ProductInventory     []proposalSnapshotProductState     `json:"product_inventory,omitempty"`
	MaterialReservations []proposalSnapshotReservationState `json:"material_reservations,omitempty"`
	ProductReservations  []proposalSnapshotReservationState `json:"product_reservations,omitempty"`
	ExpectedArrivals     []proposalSnapshotArrivalState     `json:"expected_arrivals,omitempty"`
}

type proposalSnapshotMaterialState struct {
	MaterialID   string  `json:"material_id"`
	CurrentStock float64 `json:"current_stock"`
}

type proposalSnapshotProductState struct {
	ProductID        string    `json:"product_id"`
	QuantityOnHand   float64   `json:"quantity_on_hand"`
	QuantityReserved float64   `json:"quantity_reserved"`
	AvailableFrom    time.Time `json:"available_from"`
}

type proposalSnapshotReservationState struct {
	ResourceID  string    `json:"resource_id"`
	ReservedQty float64   `json:"reserved_qty"`
	NeededAt    time.Time `json:"needed_at"`
	Status      string    `json:"status"`
}

type proposalSnapshotArrivalState struct {
	MaterialID string    `json:"material_id"`
	Quantity   float64   `json:"quantity"`
	ReadyAt    time.Time `json:"ready_at"`
	Status     string    `json:"status"`
}

type proposalSnapshotDependentJob struct {
	PlanKey             string     `json:"plan_key"`
	ProductID           string     `json:"product_id"`
	ConsumerJobStepID   string     `json:"consumer_job_step_id"`
	DependencyDepth     int        `json:"dependency_depth"`
	RequiredQty         float64    `json:"required_qty"`
	PlannedQty          float64    `json:"planned_qty"`
	PlanningStatus      string     `json:"planning_status"`
	ReasonCode          string     `json:"reason_code,omitempty"`
	EstimatedCompletion *time.Time `json:"estimated_completion,omitempty"`
}

type proposalSnapshotInventoryAction struct {
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

type proposalSnapshotJob struct {
	JobID         string    `json:"job_id"`
	ProductID     string    `json:"product_id"`
	QuantityTotal int       `json:"quantity_total"`
	Priority      string    `json:"priority"`
	Deadline      time.Time `json:"deadline"`
	Status        string    `json:"status"`
}

type proposalSnapshotPreview struct {
	ProductID       string                 `json:"product_id"`
	QuantityTotal   int                    `json:"quantity_total"`
	CanStartNow     bool                   `json:"can_start_now"`
	EarliestReadyAt *time.Time             `json:"earliest_ready_at,omitempty"`
	Steps           []proposalSnapshotStep `json:"steps"`
}

type proposalSnapshotStep struct {
	JobStepID              string                      `json:"job_step_id"`
	StepID                 string                      `json:"step_id"`
	StepSequence           int                         `json:"step_sequence"`
	QuantityTarget         int                         `json:"quantity_target"`
	MachineTypeRequired    string                      `json:"machine_type_required"`
	AllowParallelExecution bool                        `json:"allow_parallel_execution"`
	MaxParallelMachines    int                         `json:"max_parallel_machines"`
	MinSplitQty            int                         `json:"min_split_qty"`
	EstimatedDurationMins  int                         `json:"estimated_duration_mins"`
	Candidates             []proposalSnapshotCandidate `json:"candidates"`
}

type proposalSnapshotCandidate struct {
	MachineID       string    `json:"machine_id"`
	Available       bool      `json:"available"`
	AvailableFrom   time.Time `json:"available_from"`
	CapacityPerHour int       `json:"capacity_per_hour"`
}

type proposalSnapshotSlot struct {
	SlotID          string    `json:"slot_id"`
	JobStepID       string    `json:"job_step_id"`
	ProposalID      string    `json:"proposal_id"`
	MachineID       string    `json:"machine_id"`
	ScheduledStart  time.Time `json:"scheduled_start"`
	ScheduledEnd    time.Time `json:"scheduled_end"`
	QuantityPlanned int       `json:"quantity_planned"`
	Status          string    `json:"status"`
}

func (s *AIPredictiveService) GetMetrics() AIMetrics {
	runtime := AIMetrics{}
	if s.metrics != nil {
		runtime = s.metrics.Snapshot()
	}
	if s.proposalRepo == nil {
		return runtime
	}
	persisted, err := s.proposalRepo.MetricsSummary()
	if err != nil || persisted == nil {
		return runtime
	}
	runtime.ProposalGenerated = persisted.ProposalGenerated
	runtime.ProposalApproved = persisted.ProposalApproved
	runtime.ProposalRejected = persisted.ProposalRejected
	runtime.ProposalApplied = persisted.ProposalApplied
	runtime.ProposalStale = persisted.ProposalStale
	runtime.ProposalApplyFailures += persisted.ProposalApplyFailures
	runtime.SolverExecutions = persisted.SolverExecutions
	runtime.HeuristicExecutions = persisted.HeuristicExecutions
	runtime.SolverFallbacks += maxInt(persisted.ProposalGenerated-persisted.SolverExecutions-persisted.HeuristicExecutions, 0)
	runtime.RolloutState = featureflags.RolloutState()
	runtime.SolverShadowSamples = persisted.SolverShadowSamples
	runtime.AcceptanceRate = persisted.AcceptanceRate
	runtime.AvgEstimateDeviationMins = persisted.AvgEstimateDeviationMins
	runtime.AvgScrapQty = persisted.AvgScrapQty
	runtime.KpiGatePassed = !featureflags.SolverKpiGateEnabled() || (persisted.AcceptanceRate >= 0.5 && (persisted.AvgEstimateDeviationMins == 0 || persisted.AvgEstimateDeviationMins <= 120))
	return runtime
}

func (s *AIPredictiveService) RecordReadonlyExecution() {
	if s.metrics != nil {
		s.metrics.Inc(&s.metrics.ReadonlyExecutions)
	}
}

func (s *AIPredictiveService) BuildProposal(jobID string) (*SchedulingProposal, error) {
	return s.BuildProposalWithOptions(jobID, true)
}

func (s *AIPredictiveService) BuildProposalWithOptions(jobID string, includeInventoryActions bool) (*SchedulingProposal, error) {
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, err
	}
	preview, snapshotJSON, snapshotHash, err := s.buildProposalSnapshot(jobID)
	if err != nil {
		return nil, err
	}
	proposal, err := s.buildProposalForPreview(job, preview, nil, nil)
	if err != nil {
		return nil, err
	}
	proposal, err = s.finalizeProposalPlan(job, preview, proposal, proposalBuildOptions{
		BatchState:              newSubproductBatchState(s),
		IncludeInventoryActions: true,
	})
	if err != nil {
		return nil, err
	}
	if shortages, resolutions, score, err := s.analyzeProposalMaterialShortages(proposal, nil); err == nil {
		proposal.MaterialShortages = shortages
		proposal.ShortageResolutions = resolutions
		proposal.GlobalScore = score
		for _, sh := range shortages {
			if !sh.AllStepMaterialsFeasible {
				proposal.Feasible = false
				break
			}
		}
	}
	snapshotJSON, snapshotHash, err = enrichSnapshotWithProposalPlan(snapshotJSON, proposal)
	if err != nil {
		return nil, err
	}
	proposal.SnapshotHash = snapshotHash
	proposal.RolloutState = featureflags.RolloutState()
	proposal.GeneratedAt = time.Now().UTC()
	if delayRisk, err := s.GetDelayRisk(jobID); err == nil && delayRisk != nil {
		if len(delayRisk.Reasons) > 0 {
			proposal.Summary = append(proposal.Summary, "Risk level: "+delayRisk.RiskLevel+".")
		}
	}
	if s.rolloutShadowEnabled() {
		shadowMode := s.secondaryEngineMode()
		shadow, shadowErr := s.buildWithEngine(job, preview, shadowMode, nil, nil)
		if shadowErr == nil && shadow != nil {
			proposal.ShadowEngine = shadow.Engine
			proposal.ShadowObjectiveScore = shadow.ObjectiveScore
		}
	}
	_ = snapshotJSON
	return stripInventoryActionsForResponse(proposal, includeInventoryActions), nil
}

func (s *AIPredictiveService) buildProposalForPreview(job *domain.Job, preview *SolverPreview, tentativeSlots []TentativeSlot, targetCompletion *time.Time) (*SchedulingProposal, error) {
	started := time.Now()
	previewSteps := 0
	if preview != nil {
		previewSteps = len(preview.Steps)
	}
	mode := s.primaryEngineMode()
	proposal, err := s.buildWithEngine(job, preview, mode, tentativeSlots, targetCompletion)
	if err == nil {
		logger.L().Info("batch_reschedule_timing",
			zap.String("stage", "build_proposal_for_preview"),
			zap.String("job_id", job.JobID),
			zap.String("engine_mode", mode),
			zap.Int("preview_steps", previewSteps),
			zap.Int("tentative_slots", len(tentativeSlots)),
			zap.Duration("elapsed", time.Since(started)),
		)
		return proposal, nil
	}
	if mode == "preview-solver" || mode == "solver" || mode == "real-solver" {
		if s.metrics != nil {
			s.metrics.Inc(&s.metrics.SolverFallbacks)
		}
		fallback, fallbackErr := s.buildWithEngine(job, preview, "heuristic", tentativeSlots, targetCompletion)
		if fallbackErr != nil {
			return nil, fallbackErr
		}
		fallback.FallbackReason = err.Error()
		logger.L().Info("batch_reschedule_timing",
			zap.String("stage", "build_proposal_for_preview"),
			zap.String("job_id", job.JobID),
			zap.String("engine_mode", mode),
			zap.String("result", "heuristic_fallback"),
			zap.Int("preview_steps", previewSteps),
			zap.Int("tentative_slots", len(tentativeSlots)),
			zap.Duration("elapsed", time.Since(started)),
		)
		return fallback, nil
	}
	return nil, err
}

func (s *AIPredictiveService) buildWithEngine(job *domain.Job, preview *SolverPreview, mode string, tentativeSlots []TentativeSlot, targetCompletion *time.Time) (*SchedulingProposal, error) {
	switch strings.ToLower(mode) {
	case "preview-solver", "solver", "real-solver":
		if s.metrics != nil {
			s.metrics.Inc(&s.metrics.SolverExecutions)
		}
		adapter, err := s.engineAdapter(mode)
		if err != nil {
			return nil, err
		}
		ctx, cancel := context.WithTimeout(context.Background(), time.Duration(featureflags.SolverTimeoutMs())*time.Millisecond)
		defer cancel()
		proposal, err := adapter.Generate(ctx, job, preview)
		if err != nil {
			return nil, err
		}
		proposal.Engine = adapter.EngineName()
		proposal.EngineVersion = adapter.EngineVersion()
		return proposal, nil
	default:
		if s.metrics != nil {
			s.metrics.Inc(&s.metrics.HeuristicExecutions)
		}
		return s.buildHeuristicProposal(job, preview, tentativeSlots, targetCompletion)
	}
}

func (s *AIPredictiveService) engineAdapter(mode string) (ProposalEngineAdapter, error) {
	switch strings.ToLower(mode) {
	case "preview-solver", "solver":
		return NewPreviewSolverAdapter(s), nil
	case "real-solver":
		return NewRealSolverAdapter(), nil
	default:
		return nil, fmt.Errorf("unsupported engine mode %q", mode)
	}
}

func (s *AIPredictiveService) primaryEngineMode() string {
	baseMode := featureflags.ProposalEngineMode()
	if baseMode == "" {
		baseMode = "heuristic"
	}
	switch featureflags.RolloutState() {
	case "heuristic-only":
		return "heuristic"
	case "shadow":
		return "heuristic"
	case "candidate-default":
		if featureflags.SolverKpiGateEnabled() {
			if metrics := s.GetMetrics(); !metrics.KpiGatePassed {
				return "heuristic"
			}
		}
		if baseMode == "heuristic" {
			return "preview-solver"
		}
		return baseMode
	case "enforced-default":
		if baseMode == "heuristic" {
			return "preview-solver"
		}
		return baseMode
	default:
		if featureflags.SolverDefaultEnabled() && baseMode == "heuristic" {
			return "preview-solver"
		}
		return baseMode
	}
}

func (s *AIPredictiveService) secondaryEngineMode() string {
	baseMode := featureflags.ProposalEngineMode()
	if baseMode == "" || baseMode == "heuristic" {
		return "preview-solver"
	}
	return baseMode
}

func (s *AIPredictiveService) rolloutShadowEnabled() bool {
	return featureflags.SolverShadowMode() || featureflags.RolloutState() == "shadow"
}

func (s *AIPredictiveService) buildHeuristicProposal(job *domain.Job, preview *SolverPreview, tentativeSlots []TentativeSlot, targetCompletion *time.Time) (*SchedulingProposal, error) {
	strategies := selectTopStrategies(defaultHeuristicPortfolio(), 3, job, preview, tentativeSlots, targetCompletion)
	if len(strategies) == 0 {
		strategies = []HeuristicStrategy{GreedyEarliestFinish{}}
	}

	budget := 200 * time.Millisecond
	start := time.Now()
	scenarios := make([]Scenario, 0, 9)
	seen := make([]*SchedulingProposal, 0, 9)
	sharedHeuristicContext := newHeuristicContext(time.Now())

	runStrategy := func(ctx context.Context, st HeuristicStrategy) (*SchedulingProposal, error) {
		if contextual, ok := st.(contextualHeuristicStrategy); ok {
			return contextual.GenerateWithContext(ctx, s, job, preview, tentativeSlots, targetCompletion, sharedHeuristicContext)
		}
		return st.Generate(ctx, s, job, preview, tentativeSlots, targetCompletion)
	}

	addCandidate := func(p *SchedulingProposal, strategyID, scenarioID, variant string) {
		if p == nil || !p.Feasible || len(p.ProposedSlots) == 0 {
			return
		}
		p.Alternatives = nil
		for _, ex := range seen {
			if !proposalsDistinct(ex, p) {
				return
			}
		}
		seen = append(seen, p)
		scenarios = append(scenarios, Scenario{
			Proposal:    p,
			StrategyID:  strategyID,
			ScenarioID:  scenarioID,
			VariantName: variant,
		})
	}

	shiftedClone := func(base *SchedulingProposal, delta time.Duration, engineSuffix string) *SchedulingProposal {
		if base == nil {
			return nil
		}
		cp := *base
		cp.EngineVersion = cp.EngineVersion + "/" + engineSuffix
		cp.GeneratedAt = time.Now().UTC()
		cp.Alternatives = nil
		for i := range cp.ProposedSlots {
			reserved := ceilDurationTo30Min(cp.ProposedSlots[i].ScheduledEnd.Sub(cp.ProposedSlots[i].ScheduledStart))
			cp.ProposedSlots[i].ScheduledStart = alignSuccessorStart(cp.ProposedSlots[i].ScheduledStart.Add(delta))
			cp.ProposedSlots[i].ScheduledEnd = cp.ProposedSlots[i].ScheduledStart.Add(reserved)
		}
		if cp.EstimatedCompletion != nil {
			t := cp.EstimatedCompletion.Add(delta)
			cp.EstimatedCompletion = &t
		}
		return &cp
	}

	for i, st := range strategies {
		if time.Since(start) >= budget {
			break
		}
		remaining := budget - time.Since(start)
		left := len(strategies) - i
		perStrategy := remaining
		if left > 0 {
			perStrategy = remaining / time.Duration(left)
		}
		// Keep each strategy bounded so we have time for alternatives.
		if perStrategy > 120*time.Millisecond {
			perStrategy = 120 * time.Millisecond
		}
		if perStrategy < 50*time.Millisecond {
			perStrategy = 50 * time.Millisecond
		}
		if perStrategy > remaining {
			perStrategy = remaining
		}
		ctx, cancel := context.WithTimeout(context.Background(), perStrategy)
		p, err := runStrategy(ctx, st)
		cancel()
		if err != nil || p == nil {
			continue
		}

		// Variant A: as-is strategy result
		addCandidate(p, st.ID(), fmt.Sprintf("%s/A", st.ID()), "base")

		// Variant B: second-best (only defined for earliest-finish right now)
		if st.ID() == "greedy_earliest_finish" {
			ctx2, cancel2 := context.WithTimeout(context.Background(), perStrategy)
			p2, _ := runStrategy(ctx2, GreedySecondBestFinish{})
			cancel2()
			addCandidate(p2, "greedy_second_best_finish", fmt.Sprintf("%s/B", st.ID()), "second_best")
		}

		// Variant C: small what-if time shift (+30m on the aligned slot grid)
		addCandidate(shiftedClone(p, schedulerSlotGranularity, "shift_plus_30m"), st.ID(), fmt.Sprintf("%s/C", st.ID()), "shift_plus_30m")

		if len(scenarios) >= 9 {
			break
		}
	}

	if len(scenarios) == 0 {
		// Last resort: baseline behavior
		// Use a more generous timeout here so core flows (generate/apply) stay reliable even
		// when the portfolio budget is exhausted.
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		p, _ := runStrategy(ctx, GreedyEarliestFinish{})
		if p == nil {
			return nil, newSchedulingActionError(422, "reason_code=no_feasible_slot heuristic scheduler could not find any feasible slot for job "+job.JobID)
		}
		p.Alternatives = nil
		return p, nil
	}

	// Phase 4: evaluate candidates and pick a single winner.
	ev := DefaultEvaluator(time.Now())
	evalCtx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	res, _ := ev.Evaluate(evalCtx, s, job, targetCompletion, scenarios)
	if res == nil || res.Winner == nil {
		return scenarios[0].Proposal, nil
	}

	winner := res.Winner
	// Attach top 2 runners-up for debug/UI (optional)
	alts := make([]SchedulingProposal, 0, 2)
	for _, sc := range scenarios {
		if len(alts) >= 2 {
			break
		}
		if sc.Proposal == nil || sc.Proposal == winner {
			continue
		}
		if !proposalsDistinct(winner, sc.Proposal) {
			continue
		}
		cp := *sc.Proposal
		cp.Alternatives = nil
		alts = append(alts, cp)
	}
	if len(alts) > 0 {
		winner.Alternatives = alts
	}
	return winner, nil
}

func (s *AIPredictiveService) buildPreviewSolverProposal(job *domain.Job, preview *SolverPreview) (*SchedulingProposal, error) {
	proposal := &SchedulingProposal{
		JobID:          job.JobID,
		ProductID:      job.ProductID,
		Engine:         "preview-solver",
		EngineVersion:  "preview-optimizer-v2",
		GeneratedAt:    time.Now().UTC(),
		Feasible:       true,
		EarliestStart:  roundUpToHalfHour(time.Now().UTC()),
		ProposedSlots:  make([]ProposedSlot, 0),
		Summary:        make([]string, 0, 4),
		BlockedReasons: make([]string, 0, 4),
	}
	cursor := roundUpToHalfHour(time.Now().UTC())
	if preview.EarliestReadyAt != nil && preview.EarliestReadyAt.After(cursor) {
		cursor = alignSuccessorStart(*preview.EarliestReadyAt)
	}
	proposal.EarliestStart = cursor

	for _, step := range preview.Steps {
		availableCandidates := filterAvailableCandidates(step.CandidateMachines)
		if len(availableCandidates) == 0 {
			proposal.Feasible = false
			proposal.BlockedReasons = append(proposal.BlockedReasons, fmt.Sprintf("Solver found no feasible candidate machine for step %s.", step.StepName))
			continue
		}
		sort.SliceStable(availableCandidates, func(i, j int) bool {
			iFinish := availableCandidates[i].AvailableFrom.Add(time.Duration(maxInt(step.EstimatedDurationMins, 1)) * time.Minute)
			jFinish := availableCandidates[j].AvailableFrom.Add(time.Duration(maxInt(step.EstimatedDurationMins, 1)) * time.Minute)
			if iFinish.Equal(jFinish) {
				return availableCandidates[i].CapacityPerHour > availableCandidates[j].CapacityPerHour
			}
			return iFinish.Before(jFinish)
		})

		parallelCount := 1
		if step.AllowParallelExecution && step.MaxParallelMachines > 1 && len(availableCandidates) > 1 && step.QuantityTarget >= maxInt(step.MinSplitQty, 1)*2 {
			parallelCount = minInt(step.MaxParallelMachines, len(availableCandidates))
			if parallelCount > 2 {
				parallelCount = 2
			}
		}

		selected := availableCandidates[:parallelCount]
		start := cursor
		for _, candidate := range selected {
			if candidate.AvailableFrom.After(start) {
				start = candidate.AvailableFrom
			}
		}
		start = alignSuccessorStart(start)
		durationMetrics := stepDurationMetrics(domain.ProcessSteps{
			DefaultProcessingTime: maxInt(step.EstimatedDurationMins, 1),
		}, selected, float64(step.QuantityTarget))
		allocations := make([]int, parallelCount)
		if parallelCount == 1 {
			allocations[0] = step.QuantityTarget
		} else {
			for i, qty := range allocateSplitQuantities(step.QuantityTarget, equalPercents(parallelCount), parallelCount, step.MinBatchSize) {
				allocations[i] = qty
			}
		}
		stepEnd := start
		for idx, candidate := range selected {
			end := start.Add(durationMetrics.ReservedDuration)
			if end.After(stepEnd) {
				stepEnd = end
			}
			proposal.ProposedSlots = append(proposal.ProposedSlots, ProposedSlot{
				JobStepID:             step.JobStepID,
				StepID:                step.StepID,
				StepName:              step.StepName,
				MachineID:             candidate.MachineID,
				MachineName:           candidate.MachineName,
				ScheduledStart:        start,
				ScheduledEnd:          end,
				QuantityPlanned:       allocations[idx],
				AllocationPercent:     float64(allocations[idx]) / float64(step.QuantityTarget) * 100,
				IsParallel:            parallelCount > 1,
				BatchSequence:         idx + 1,
				ActualDurationMins:    durationMetrics.ActualDurationMins,
				EstimatedDurationMins: durationMetrics.ReservedDurationMins,
				ReservedDurationMins:  durationMetrics.ReservedDurationMins,
				RoundingOverheadMins:  durationMetrics.RoundingOverheadMins,
				Reasoning: []string{
					"Preview optimizer selected the machine combination with the earliest projected completion.",
					fmt.Sprintf("Machine %s was chosen because it minimizes finish time under current readiness and availability.", candidate.MachineName),
				},
			})
		}
		proposal.Summary = append(proposal.Summary, fmt.Sprintf("Optimizer scheduled step %s using %d machine(s).", step.StepName, parallelCount))
		cursor = alignSuccessorStart(stepEnd.Add(time.Duration(step.MinWaitMinutes+step.TransferMinutes) * time.Minute))
	}

	finalizeProposalScores(proposal, job)
	return proposal, nil
}

func filterAvailableCandidates(candidates []CandidateMachine) []CandidateMachine {
	out := make([]CandidateMachine, 0, len(candidates))
	for _, candidate := range candidates {
		if candidate.Available || candidate.AvailableFrom.After(time.Time{}) {
			out = append(out, candidate)
		}
	}
	return out
}

func equalPercents(count int) []float64 {
	if count <= 0 {
		return nil
	}
	out := make([]float64, count)
	base := 100.0 / float64(count)
	for i := range out {
		out[i] = base
	}
	return out
}

func finalizeProposalScores(proposal *SchedulingProposal, job *domain.Job) {
	if proposal == nil || job == nil {
		return
	}
	if proposal.Feasible {
		completion := proposal.EarliestStart
		if len(proposal.ProposedSlots) > 0 {
			completion = proposal.ProposedSlots[0].ScheduledEnd
			for _, slot := range proposal.ProposedSlots {
				if slot.ScheduledEnd.After(completion) {
					completion = slot.ScheduledEnd
				}
			}
		}
		proposal.EstimatedCompletion = &completion
	}
	if len(proposal.Summary) == 0 {
		proposal.Summary = append(proposal.Summary, "No proposal steps were generated.")
	}
	if !proposal.Feasible {
		proposal.Summary = append(proposal.Summary, "Proposal is partially blocked and needs planner review.")
	}
	score := 1000.0
	if proposal.EstimatedCompletion != nil && proposal.EstimatedCompletion.After(job.Deadline) {
		score -= proposal.EstimatedCompletion.Sub(job.Deadline).Minutes()
	}
	score -= float64(len(proposal.BlockedReasons) * 100)
	score -= float64(len(proposal.ProposedSlots) * 5)
	proposal.ObjectiveScore = score
}

func (s *AIPredictiveService) buildProposalSnapshot(jobID string) (*SolverPreview, string, string, error) {
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, "", "", err
	}
	preview, err := s.scheduling.BuildSolverPreview(jobID)
	if err != nil {
		return nil, "", "", err
	}
	slots, err := s.slotRepo.ListByJobID(jobID)
	if err != nil {
		return nil, "", "", err
	}
	machineIDs, qVec, uVec, err := s.buildSchedulingContextVectors(time.Now().UTC(), nil)
	if err != nil {
		return nil, "", "", err
	}
	sort.Slice(slots, func(i, j int) bool { return slots[i].SlotID < slots[j].SlotID })
	payload := proposalSnapshot{
		Job: proposalSnapshotJob{
			JobID:         job.JobID,
			ProductID:     job.ProductID,
			QuantityTotal: job.QuantityTotal,
			Priority:      job.Priority,
			Deadline:      roundToMinute(job.Deadline),
			Status:        job.Status,
		},
		Preview:                  normalizePreview(preview),
		ExistingSlots:            normalizeSnapshotSlots(slots),
		Inventory:                s.buildInventorySnapshot(),
		MachineIDs:               machineIDs,
		QueueLengthsVector:       qVec,
		MachineUtilizationVector: uVec,
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return nil, "", "", err
	}
	sum := sha256.Sum256(raw)
	return preview, string(raw), hex.EncodeToString(sum[:]), nil
}

// buildProposalSnapshotWithTentative builds snapshot for batch scheduling,
// using tentative slots from earlier jobs in the batch when computing preview.
func (s *AIPredictiveService) buildProposalSnapshotWithTentative(jobID string, tentativeSlots []TentativeSlot, earliestFloor *time.Time) (*SolverPreview, string, string, error) {
	started := time.Now()
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, "", "", err
	}
	preview, err := s.scheduling.BuildSolverPreviewWithTentativeSlotsAndFloor(jobID, tentativeSlots, earliestFloor)
	if err != nil {
		return nil, "", "", err
	}
	slots, err := s.slotRepo.ListByJobID(jobID)
	if err != nil {
		return nil, "", "", err
	}
	machineIDs, qVec, uVec, err := s.buildSchedulingContextVectors(time.Now().UTC(), tentativeSlots)
	if err != nil {
		return nil, "", "", err
	}
	sort.Slice(slots, func(i, j int) bool { return slots[i].SlotID < slots[j].SlotID })
	payload := proposalSnapshot{
		Job: proposalSnapshotJob{
			JobID:         job.JobID,
			ProductID:     job.ProductID,
			QuantityTotal: job.QuantityTotal,
			Priority:      job.Priority,
			Deadline:      roundToMinute(job.Deadline),
			Status:        job.Status,
		},
		Preview:                  normalizePreview(preview),
		ExistingSlots:            normalizeSnapshotSlots(slots),
		Inventory:                s.buildInventorySnapshot(),
		MachineIDs:               machineIDs,
		QueueLengthsVector:       qVec,
		MachineUtilizationVector: uVec,
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return nil, "", "", err
	}
	sum := sha256.Sum256(raw)
	logger.L().Info("batch_reschedule_timing",
		zap.String("stage", "build_proposal_snapshot_with_tentative"),
		zap.String("job_id", jobID),
		zap.Int("tentative_slots", len(tentativeSlots)),
		zap.Int("preview_steps", len(preview.Steps)),
		zap.Int("existing_slots", len(slots)),
		zap.Duration("elapsed", time.Since(started)),
	)
	return preview, string(raw), hex.EncodeToString(sum[:]), nil
}

func normalizePreview(preview *SolverPreview) proposalSnapshotPreview {
	if preview == nil {
		return proposalSnapshotPreview{}
	}
	result := proposalSnapshotPreview{
		ProductID:     preview.ProductID,
		QuantityTotal: preview.QuantityTotal,
		CanStartNow:   preview.CanStartNow,
	}
	if preview.EarliestReadyAt != nil {
		rounded := roundToMinute(*preview.EarliestReadyAt)
		result.EarliestReadyAt = &rounded
	}
	for _, step := range preview.Steps {
		snapshotStep := proposalSnapshotStep{
			JobStepID:              step.JobStepID,
			StepID:                 step.StepID,
			StepSequence:           step.StepSequence,
			QuantityTarget:         step.QuantityTarget,
			MachineTypeRequired:    step.MachineTypeRequired,
			AllowParallelExecution: step.AllowParallelExecution,
			MaxParallelMachines:    step.MaxParallelMachines,
			MinSplitQty:            step.MinSplitQty,
			EstimatedDurationMins:  step.EstimatedDurationMins,
		}
		for _, candidate := range step.CandidateMachines {
			snapshotStep.Candidates = append(snapshotStep.Candidates, proposalSnapshotCandidate{
				MachineID:       candidate.MachineID,
				Available:       candidate.Available,
				AvailableFrom:   roundToMinute(candidate.AvailableFrom),
				CapacityPerHour: candidate.CapacityPerHour,
			})
		}
		result.Steps = append(result.Steps, snapshotStep)
	}
	return result
}

func normalizeSnapshotSlots(slots []domain.JobStepScheduleSlots) []proposalSnapshotSlot {
	result := make([]proposalSnapshotSlot, 0, len(slots))
	for _, slot := range slots {
		result = append(result, proposalSnapshotSlot{
			SlotID:          slot.SlotID,
			JobStepID:       slot.JobStepID,
			ProposalID:      slot.ProposalID,
			MachineID:       slot.MachineID,
			ScheduledStart:  roundToMinute(slot.ScheduledStart),
			ScheduledEnd:    roundToMinute(slot.ScheduledEnd),
			QuantityPlanned: slot.QuantityPlanned,
			Status:          slot.Status,
		})
	}
	return result
}

func (s *AIPredictiveService) buildInventorySnapshot() proposalSnapshotInventory {
	inv := proposalSnapshotInventory{}
	if s.scheduling == nil || s.scheduling.inventoryRepo == nil {
		return inv
	}
	if materials, err := s.scheduling.inventoryRepo.ListMaterials(); err == nil {
		sort.Slice(materials, func(i, j int) bool { return materials[i].MaterialID < materials[j].MaterialID })
		for _, material := range materials {
			inv.Materials = append(inv.Materials, proposalSnapshotMaterialState{
				MaterialID:   material.MaterialID,
				CurrentStock: material.CurrentStock,
			})
		}
	}
	if arrivals, err := s.scheduling.inventoryRepo.ListExpectedArrivals("", nil, nil, ""); err == nil {
		sort.Slice(arrivals, func(i, j int) bool {
			if arrivals[i].MaterialID == arrivals[j].MaterialID {
				return arrivals[i].ExpectedArriveAt.Before(arrivals[j].ExpectedArriveAt)
			}
			return arrivals[i].MaterialID < arrivals[j].MaterialID
		})
		for _, arrival := range arrivals {
			inv.ExpectedArrivals = append(inv.ExpectedArrivals, proposalSnapshotArrivalState{
				MaterialID: arrival.MaterialID,
				Quantity:   arrival.Quantity,
				ReadyAt:    alignSuccessorStart(arrival.ExpectedArriveAt.UTC()),
				Status:     arrival.Status,
			})
		}
	}
	if productInventory, err := s.scheduling.inventoryRepo.ListProductInventory(); err == nil {
		sort.Slice(productInventory, func(i, j int) bool {
			if productInventory[i].ProductID == productInventory[j].ProductID {
				return productInventory[i].AvailableFrom.Before(productInventory[j].AvailableFrom)
			}
			return productInventory[i].ProductID < productInventory[j].ProductID
		})
		for _, record := range productInventory {
			inv.ProductInventory = append(inv.ProductInventory, proposalSnapshotProductState{
				ProductID:        record.ProductID,
				QuantityOnHand:   record.QuantityOnHand,
				QuantityReserved: record.QuantityReserved,
				AvailableFrom:    alignSuccessorStart(record.AvailableFrom.UTC()),
			})
		}
	}
	if reservations, err := s.scheduling.inventoryRepo.ListReservations("", ""); err == nil {
		sort.Slice(reservations, func(i, j int) bool {
			if reservations[i].MaterialID == reservations[j].MaterialID {
				return reservations[i].NeededAt.Before(reservations[j].NeededAt)
			}
			return reservations[i].MaterialID < reservations[j].MaterialID
		})
		for _, reservation := range reservations {
			inv.MaterialReservations = append(inv.MaterialReservations, proposalSnapshotReservationState{
				ResourceID:  reservation.MaterialID,
				ReservedQty: reservation.ReservedQty,
				NeededAt:    alignSuccessorStart(reservation.NeededAt.UTC()),
				Status:      reservation.Status,
			})
		}
	}
	if reservations, err := s.scheduling.inventoryRepo.ListProductReservations("", ""); err == nil {
		sort.Slice(reservations, func(i, j int) bool {
			if reservations[i].ProductID == reservations[j].ProductID {
				return reservations[i].NeededAt.Before(reservations[j].NeededAt)
			}
			return reservations[i].ProductID < reservations[j].ProductID
		})
		for _, reservation := range reservations {
			inv.ProductReservations = append(inv.ProductReservations, proposalSnapshotReservationState{
				ResourceID:  reservation.ProductID,
				ReservedQty: reservation.ReservedQty,
				NeededAt:    alignSuccessorStart(reservation.NeededAt.UTC()),
				Status:      reservation.Status,
			})
		}
	}
	return inv
}

func enrichSnapshotWithProposalPlan(baseJSON string, proposal *SchedulingProposal) (string, string, error) {
	var payload proposalSnapshot
	if err := json.Unmarshal([]byte(baseJSON), &payload); err != nil {
		return "", "", err
	}
	if proposal != nil {
		payload.DependentJobs = normalizeSnapshotDependentJobs(proposal.DependentJobs)
		payload.InventoryActions = normalizeSnapshotInventoryActions(proposal.InventoryActions)
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return "", "", err
	}
	sum := sha256.Sum256(raw)
	return string(raw), hex.EncodeToString(sum[:]), nil
}

func normalizeSnapshotDependentJobs(items []DependentJobPlan) []proposalSnapshotDependentJob {
	out := make([]proposalSnapshotDependentJob, 0, len(items))
	for _, item := range items {
		out = append(out, proposalSnapshotDependentJob{
			PlanKey:             item.PlanKey,
			ProductID:           item.ProductID,
			ConsumerJobStepID:   item.ConsumerJobStepID,
			DependencyDepth:     item.DependencyDepth,
			RequiredQty:         item.RequiredQty,
			PlannedQty:          item.PlannedQty,
			PlanningStatus:      item.PlanningStatus,
			ReasonCode:          item.ReasonCode,
			EstimatedCompletion: normalizeSnapshotTime(item.EstimatedCompletion),
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].PlanKey < out[j].PlanKey })
	return out
}

func normalizeSnapshotInventoryActions(items []InventoryAction) []proposalSnapshotInventoryAction {
	out := make([]proposalSnapshotInventoryAction, 0, len(items))
	for _, item := range items {
		out = append(out, proposalSnapshotInventoryAction{
			Sequence:    item.Sequence,
			ActionType:  item.ActionType,
			ResourceID:  item.ResourceID,
			JobID:       item.JobID,
			JobStepID:   item.JobStepID,
			Quantity:    item.Quantity,
			EffectiveAt: alignSuccessorStart(item.EffectiveAt.UTC()),
			ReasonCode:  item.ReasonCode,
			PlanKey:     item.PlanKey,
		})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Sequence == out[j].Sequence {
			return out[i].ActionType < out[j].ActionType
		}
		return out[i].Sequence < out[j].Sequence
	})
	return out
}

func normalizeSnapshotTime(v *time.Time) *time.Time {
	if v == nil {
		return nil
	}
	t := alignSuccessorStart(v.UTC())
	return &t
}

func roundToMinute(v time.Time) time.Time {
	if v.IsZero() {
		return v
	}
	return v.UTC().Truncate(time.Minute)
}

func (s *AIPredictiveService) buildSchedulingContextVectors(now time.Time, tentativeSlots []TentativeSlot) ([]string, []int, []float64, error) {
	machines, err := s.machineRepo.ListAll()
	if err != nil {
		return nil, nil, nil, err
	}
	sort.Slice(machines, func(i, j int) bool { return machines[i].MachineID < machines[j].MachineID })
	machineIDs := make([]string, 0, len(machines))
	indexByMachine := make(map[string]int, len(machines))
	for i, m := range machines {
		machineIDs = append(machineIDs, m.MachineID)
		indexByMachine[m.MachineID] = i
	}

	active, err := s.slotRepo.ListActiveByJobIDs(nil)
	if err != nil {
		return nil, nil, nil, err
	}

	queue := make([]int, len(machines))
	utilMinutes := make([]int, len(machines))
	windowStart := now
	windowEnd := now.Add(24 * time.Hour)

	addInterval := func(machineID string, start, end time.Time, countsAsQueue bool) {
		idx, ok := indexByMachine[machineID]
		if !ok {
			return
		}
		if countsAsQueue {
			queue[idx]++
		}
		// utilization only counts time overlapping [windowStart, windowEnd)
		if end.After(windowStart) && start.Before(windowEnd) {
			s0 := start
			if s0.Before(windowStart) {
				s0 = windowStart
			}
			e0 := end
			if e0.After(windowEnd) {
				e0 = windowEnd
			}
			if e0.After(s0) {
				utilMinutes[idx] += int(e0.Sub(s0).Minutes())
			}
		}
	}

	for _, row := range active {
		addInterval(row.MachineID, row.ScheduledStart, row.ScheduledEnd, true)
	}
	for _, ts := range tentativeSlots {
		addInterval(ts.MachineID, ts.ScheduledStart, ts.ScheduledEnd, true)
	}

	util := make([]float64, len(machines))
	denom := float64(24 * 60)
	for i := range util {
		u := float64(utilMinutes[i]) / denom
		if u > 1 {
			u = 1
		}
		if math.IsNaN(u) || math.IsInf(u, 0) || u < 0 {
			u = 0
		}
		util[i] = u
	}
	return machineIDs, queue, util, nil
}

func (s *AIPredictiveService) GenerateProposal(jobID, generatedBy string) (*SchedulingProposal, error) {
	return s.GenerateProposalWithOptions(jobID, generatedBy, true)
}

func (s *AIPredictiveService) GenerateProposalWithOptions(jobID, generatedBy string, includeInventoryActions bool) (*SchedulingProposal, error) {
	if s.proposalRepo == nil {
		return nil, fmt.Errorf("proposal repository is not configured")
	}
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, err
	}
	preview, snapshotJSON, snapshotHash, err := s.buildProposalSnapshot(jobID)
	if err != nil {
		return nil, err
	}
	proposal, err := s.buildProposalForPreview(job, preview, nil, nil)
	if err != nil {
		return nil, err
	}
	proposal, err = s.finalizeProposalPlan(job, preview, proposal, proposalBuildOptions{
		BatchState:              newSubproductBatchState(s),
		IncludeInventoryActions: true,
	})
	if err != nil {
		return nil, err
	}
	if shortages, resolutions, score, err := s.analyzeProposalMaterialShortages(proposal, nil); err == nil {
		proposal.MaterialShortages = shortages
		proposal.ShortageResolutions = resolutions
		proposal.GlobalScore = score
		for _, sh := range shortages {
			if !sh.AllStepMaterialsFeasible {
				proposal.Feasible = false
				break
			}
		}
	}
	snapshotJSON, snapshotHash, err = enrichSnapshotWithProposalPlan(snapshotJSON, proposal)
	if err != nil {
		return nil, err
	}
	// Compute shadow comparison when rollout/shadow mode is active.
	if s.rolloutShadowEnabled() {
		shadowMode := s.secondaryEngineMode()
		if shadowMode != "" && shadowMode != s.primaryEngineMode() {
			shadow, shadowErr := s.buildWithEngine(job, preview, shadowMode, nil, nil)
			if shadowErr == nil && shadow != nil {
				proposal.ShadowEngine = shadow.Engine
				proposal.ShadowObjectiveScore = shadow.ObjectiveScore
			}
		}
	}
	delayRisk, _ := s.GetDelayRisk(jobID)
	version, err := s.proposalRepo.NextVersion(jobID)
	if err != nil {
		return nil, err
	}
	proposalID := id.NewPrefixed("AIPROP-")
	proposal.ProposalID = proposalID
	proposal.Version = version
	proposal.Status = domain.AIProposalStatusDraft
	proposal.SnapshotHash = snapshotHash
	now := time.Now().UTC()
	record := &domain.AIProposal{
		ProposalID:           proposalID,
		JobID:                jobID,
		Version:              version,
		Status:               domain.AIProposalStatusDraft,
		RolloutState:         featureflags.RolloutState(),
		Engine:               proposal.Engine,
		EngineVersion:        proposal.EngineVersion,
		ObjectiveScore:       proposal.ObjectiveScore,
		ShadowEngine:         proposal.ShadowEngine,
		ShadowObjectiveScore: proposal.ShadowObjectiveScore,
		FallbackReason:       proposal.FallbackReason,
		InputHash:            snapshotHash,
		SummaryText:          strings.Join(proposal.Summary, "\n"),
		GeneratedBy:          defaultActor(generatedBy),
		GeneratedAt:          now,
		CreatedAt:            now,
		UpdatedAt:            now,
		SnapshotJSON:         snapshotJSON,
		ProposalJSON:         mustJSON(canonicalProposalForPersistence(proposal)),
		ShadowProposalJSON: func() string {
			if proposal.ShadowEngine == "" {
				return ""
			}
			return mustJSON(map[string]interface{}{
				"shadow_engine":          proposal.ShadowEngine,
				"shadow_objective_score": proposal.ShadowObjectiveScore,
			})
		}(),
		EstimatedCompletionAt: proposal.EstimatedCompletion,
		OutcomeStatus:         "pending_execution",
	}
	if delayRisk != nil {
		record.RiskLevel = delayRisk.RiskLevel
		record.RiskScore = delayRisk.RiskScore
	}
	if err := s.proposalRepo.Create(record); err != nil {
		return nil, err
	}
	if err := s.proposalRepo.MarkOtherDraftsStale(jobID, proposalID, now); err != nil {
		return nil, err
	}
	if s.scheduling != nil {
		if err := s.scheduling.CaptureMLTrainingEventForProposalRecord(record, proposal); err != nil {
			logger.L().Warn("ai_proposal_ml_training_capture_failed",
				zap.String("proposal_id", proposalID),
				zap.String("job_id", jobID),
				zap.Error(err),
			)
		}
	}
	if s.metrics != nil {
		s.metrics.Inc(&s.metrics.ProposalGenerated)
	}
	logger.L().Info("ai_proposal_generated",
		zap.String("proposal_id", proposalID),
		zap.String("job_id", jobID),
		zap.String("engine", proposal.Engine),
		zap.String("generated_by", defaultActor(generatedBy)),
	)
	return stripInventoryActionsForResponse(proposal, includeInventoryActions), nil
}

func (s *AIPredictiveService) ListProposals(jobID string, includeStale bool) ([]domain.AIProposal, error) {
	list, err := s.proposalRepo.ListByJobID(jobID)
	if err != nil {
		return nil, err
	}
	if includeStale {
		return list, nil
	}
	// Exclude stale by default so frontend doesn't mix old and new proposals.
	filtered := make([]domain.AIProposal, 0, len(list))
	for _, p := range list {
		if p.Status != domain.AIProposalStatusStale {
			filtered = append(filtered, p)
		}
	}
	return filtered, nil
}

func (s *AIPredictiveService) GetProposal(proposalID string) (*SchedulingProposal, error) {
	record, err := s.proposalRepo.GetByID(proposalID)
	if err != nil {
		return nil, err
	}
	return s.decodeProposalRecord(record)
}

func (s *AIPredictiveService) ApproveProposal(proposalID, approvedBy, notes string) (*domain.AIProposal, error) {
	return s.ApproveProposalWithOpts(proposalID, approvedBy, notes, false)
}

func (s *AIPredictiveService) ApproveProposalWithOpts(proposalID, approvedBy, notes string, skipStalenessCheck bool) (*domain.AIProposal, error) {
	record, err := s.proposalRepo.GetByID(proposalID)
	if err != nil {
		return nil, err
	}
	// Staleness: skip when (a) feature flag, or (b) batch flow (skip_staleness_check=true).
	if !featureflags.ApplySkipStalenessCheck() && !skipStalenessCheck {
		if err := s.ensureProposalFresh(record); err != nil {
			return nil, err
		}
	}
	if record.Status != domain.AIProposalStatusDraft {
		return nil, newSchedulingActionError(422, "only draft proposals can be approved")
	}
	proposal, err := s.decodeProposalRecord(record)
	if err != nil {
		return nil, err
	}
	if !proposal.Feasible {
		msg := "proposal is not fully feasible and cannot be approved"
		if len(proposal.BlockedReasons) > 0 {
			msg += ": " + proposal.BlockedReasons[0]
		}
		return nil, newSchedulingActionError(422, msg)
	}
	now := time.Now().UTC()
	record.Status = domain.AIProposalStatusApproved
	record.ApprovedBy = defaultActor(approvedBy)
	record.ApprovalNotes = notes
	record.ApprovedAt = &now
	record.UpdatedAt = now
	if err := s.proposalRepo.Update(record); err != nil {
		return nil, err
	}
	if s.metrics != nil {
		s.metrics.Inc(&s.metrics.ProposalApproved)
	}
	logger.L().Info("ai_proposal_approved",
		zap.String("proposal_id", proposalID),
		zap.String("approved_by", record.ApprovedBy),
	)
	return record, nil
}

func (s *AIPredictiveService) RejectProposal(proposalID, rejectedBy, reason string) (*domain.AIProposal, error) {
	record, err := s.proposalRepo.GetByID(proposalID)
	if err != nil {
		return nil, err
	}
	if record.Status == domain.AIProposalStatusApplied {
		return nil, newSchedulingActionError(422, "applied proposals cannot be rejected")
	}
	if record.Status == domain.AIProposalStatusRejected {
		return nil, newSchedulingActionError(409, "proposal is already rejected")
	}
	now := time.Now().UTC()
	record.Status = domain.AIProposalStatusRejected
	record.RejectedBy = defaultActor(rejectedBy)
	record.RejectionReason = reason
	record.RejectedAt = &now
	record.UpdatedAt = now
	if err := s.proposalRepo.Update(record); err != nil {
		return nil, err
	}
	if s.metrics != nil {
		s.metrics.Inc(&s.metrics.ProposalRejected)
	}
	logger.L().Info("ai_proposal_rejected",
		zap.String("proposal_id", proposalID),
		zap.String("rejected_by", record.RejectedBy),
	)
	return record, nil
}

func (s *AIPredictiveService) ApplyProposal(jobID string) (*AppliedProposalResult, error) {
	if !featureflags.CompatibilityApplyEnabled() {
		return nil, newSchedulingActionError(409, "job-based apply-proposal is disabled; use persisted proposal approval and /ai/scheduling/proposals/:id/apply instead")
	}
	proposal, err := s.GenerateProposal(jobID, "system")
	if err != nil {
		return nil, err
	}
	// Compatibility flow mutates state between approve/apply, so bypass staleness checks.
	if _, err := s.ApproveProposalWithOpts(proposal.ProposalID, "system", "compatibility apply auto-approval", true); err != nil {
		return nil, err
	}
	return s.ApplyProposalByIDWithOpts(proposal.ProposalID, "system", "compat-"+jobID, true)
}

func (s *AIPredictiveService) ApplyProposalByID(proposalID, appliedBy, idempotencyKey string) (*AppliedProposalResult, error) {
	return s.ApplyProposalByIDWithOpts(proposalID, appliedBy, idempotencyKey, false)
}

func (s *AIPredictiveService) ApplyProposalByIDWithOpts(proposalID, appliedBy, idempotencyKey string, skipStalenessCheck bool) (*AppliedProposalResult, error) {
	if s.jobSlotService == nil || s.proposalRepo == nil || s.db == nil {
		return nil, fmt.Errorf("proposal application is not fully configured")
	}
	record, err := s.proposalRepo.GetByID(proposalID)
	if err != nil {
		return nil, err
	}
	// Idempotency: if already applied with the same key, return the previous result.
	if record.Status == domain.AIProposalStatusApplied {
		if idempotencyKey != "" && record.IdempotencyKey == idempotencyKey {
			proposal, decodeErr := s.decodeProposalRecord(record)
			if decodeErr != nil {
				return nil, decodeErr
			}
			return &AppliedProposalResult{
				ProposalID:       record.ProposalID,
				JobID:            record.JobID,
				AppliedAt:        derefTime(record.AppliedAt),
				AppliedSlotCount: len(proposal.ProposedSlots),
				Message:          "Proposal was already applied with the same idempotency key.",
				IdempotencyKey:   idempotencyKey,
				Proposal:         proposal,
			}, nil
		}
		return nil, newSchedulingActionError(409, "proposal is already applied")
	}
	// Status gate: check approval BEFORE staleness so callers get the correct
	// semantic error regardless of whether the underlying data has changed.
	if featureflags.ProposalApplyRequiresApproval() && record.Status != domain.AIProposalStatusApproved {
		return nil, newSchedulingActionError(422, "proposal must be approved before apply")
	}
	if !featureflags.ProposalApplyRequiresApproval() &&
		record.Status != domain.AIProposalStatusApproved &&
		record.Status != domain.AIProposalStatusDraft {
		return nil, newSchedulingActionError(422, "proposal must be draft or approved before apply")
	}
	// Stale detection: skip when (a) feature flag, or (b) batch apply (skip_staleness_check=true).
	// Batch apply: applying proposal 2+ after 1 changes DB state; staleness would always trigger.
	if !featureflags.ApplySkipStalenessCheck() && !skipStalenessCheck {
		if err := s.ensureProposalFresh(record); err != nil {
			if s.metrics != nil {
				s.metrics.Inc(&s.metrics.ProposalApplyFailures)
			}
			return nil, err
		}
	}
	proposal, err := s.decodeProposalRecord(record)
	if err != nil {
		return nil, err
	}
	if !proposal.Feasible {
		msg := "proposal is not fully feasible"
		if len(proposal.BlockedReasons) > 0 {
			msg += ": " + proposal.BlockedReasons[0]
		}
		return nil, newSchedulingActionError(422, msg)
	}

	var createdIDs []string
	var createdJobIDs []string
	var createdDependencyLinks []CreatedDependencyLink
	applyFn := func(tx *gorm.DB) error {
		txSlotRepo := repository.NewJobSlotRepository(tx)
		txStepRepo := repository.NewJobStepRepository(tx)
		txJobRepo := repository.NewJobRepository(tx)
		txProcessRepo := repository.NewProcessRepository(tx)
		txScheduling := s.scheduling.WithTransaction(tx)
		txSlotService := NewJobSlotService(txSlotRepo, txStepRepo, txProcessRepo, txJobRepo, txScheduling)
		existing, err := txSlotRepo.ListByJobID(record.JobID)
		if err != nil {
			return err
		}
		for _, slot := range existing {
			if slot.Status != domain.SlotStatusCancelled {
				return newSchedulingActionError(409, "job already has active slots; proposal apply supports unscheduled jobs only")
			}
		}
		// Repair persisted proposal against live machine occupancy/calendar at apply-time.
		// Apply All may run over proposals generated earlier; this keeps apply from failing
		// on overlap/calendar drift when a repairable alternative exists.
		activeRows, err := txSlotRepo.ListActiveByJobIDs(nil)
		if err != nil {
			return err
		}
		liveTentative := tentativeSlotsFromActiveRows(activeRows, map[string]bool{record.JobID: true})
		repairTargets := []*SchedulingProposal{proposal}
		if err := s.chainAwareForwardRepair(repairTargets, chainRepairPassBudget(repairTargets), liveTentative, nil); err != nil {
			return err
		}
		if err := s.validateProposalSlotsStrict(record.JobID, proposal); err != nil {
			return err
		}
		createdPlanJobs, createdPlanSteps, childJobIDs, dependencyLinks, err := s.createDependentJobsAndApply(tx, proposal, record.ProposalID)
		if err != nil {
			return err
		}
		createdJobIDs = append(createdJobIDs, childJobIDs...)
		createdDependencyLinks = append(createdDependencyLinks, dependencyLinks...)
		remappedActions := remapActionJobIDs(proposal.InventoryActions, record.JobID, createdPlanJobs, createdPlanSteps)
		if err := s.allocateProposalReservations(tx, remappedActions, plannedDependentPlanKeys(proposal.DependentJobs)); err != nil {
			return err
		}
		normalizedSlots, err := normalizeLegacySplitFallbackSlots(proposal.ProposedSlots, txStepRepo, txProcessRepo)
		if err != nil {
			return err
		}
		// Normalize can rewrite slice timings (legacy fallback) and dependent-child creation above
		// may add machine occupancy in this same transaction. Re-repair against current tx state.
		normalizedRepair := &SchedulingProposal{
			JobID:         record.JobID,
			ProposedSlots: append([]ProposedSlot(nil), normalizedSlots...),
		}
		activeRowsAfterDeps, err := txSlotRepo.ListActiveByJobIDs(nil)
		if err != nil {
			return err
		}
		liveTentativeAfterDeps := tentativeSlotsFromActiveRows(activeRowsAfterDeps, map[string]bool{record.JobID: true})
		repairTargetsAfterDeps := []*SchedulingProposal{normalizedRepair}
		if err := s.chainAwareForwardRepair(repairTargetsAfterDeps, chainRepairPassBudget(repairTargetsAfterDeps), liveTentativeAfterDeps, nil); err != nil {
			return err
		}
		if err := s.validateProposalSlotsStrict(record.JobID, normalizedRepair); err != nil {
			return err
		}
		normalizedSlots = normalizedRepair.ProposedSlots
		grouped := make(map[string][]dto.CreateSlotRequest)
		order := make([]string, 0)
		seen := make(map[string]bool)
		for _, proposed := range normalizedSlots {
			durationMins := maxInt(proposed.EstimatedDurationMins, 1)
			if proposed.ScheduledEnd.After(proposed.ScheduledStart) {
				derived := int(proposed.ScheduledEnd.Sub(proposed.ScheduledStart).Minutes())
				if derived > 0 {
					durationMins = derived
				}
			}
			if !seen[proposed.JobStepID] {
				seen[proposed.JobStepID] = true
				order = append(order, proposed.JobStepID)
			}
			grouped[proposed.JobStepID] = append(grouped[proposed.JobStepID], dto.CreateSlotRequest{
				JobStepID:         proposed.JobStepID,
				ProposalID:        record.ProposalID,
				MachineID:         proposed.MachineID,
				StartTime:         proposed.ScheduledStart.Format(time.RFC3339),
				DurationMins:      durationMins,
				Quantity:          proposed.QuantityPlanned,
				SplitGroupID:      record.ProposalID,
				AllocationPercent: proposed.AllocationPercent,
				IsParallel:        proposed.IsParallel,
				BatchSequence:     proposed.BatchSequence,
				ProcessingMins:    durationMins,
			})
		}
		sort.Slice(order, func(i, j int) bool {
			si, _ := txStepRepo.GetByID(order[i])
			sj, _ := txStepRepo.GetByID(order[j])
			if si == nil || sj == nil {
				return i < j
			}
			return si.StepSequence < sj.StepSequence
		})
		var chainPrevEnd *time.Time
		for _, jobStepID := range order {
			ignoreMinSplitQty := isTemporalSliceRequestGroup(grouped[jobStepID])
			sort.SliceStable(grouped[jobStepID], func(i, j int) bool {
				return grouped[jobStepID][i].StartTime < grouped[jobStepID][j].StartTime
			})
			var previousEnd *time.Time
			stepMaxEnd := time.Time{}
			// Pre-validate each proposed slot so we can return a precise, actionable
			// error message instead of a generic validation string.
			for i := range grouped[jobStepID] {
				rs := &grouped[jobStepID][i]
				start, parseErr := time.Parse(time.RFC3339, rs.StartTime)
				if parseErr != nil {
					return newSchedulingActionError(422, "invalid proposed slot start time: "+rs.StartTime)
				}
				if chainPrevEnd != nil && chainPrevEnd.After(start) {
					start = alignSuccessorStart(*chainPrevEnd)
					rs.StartTime = start.Format(time.RFC3339)
				}
				if previousEnd != nil && previousEnd.After(start) {
					start = alignSuccessorStart(*previousEnd)
					rs.StartTime = start.Format(time.RFC3339)
				}
				end := start.Add(time.Duration(rs.DurationMins) * time.Minute)
				validation, vErr := txScheduling.ValidateSlotWithOptions(jobStepID, rs.MachineID, start, end, rs.Quantity, "", SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitQty})
				if vErr != nil {
					return vErr
				}
				if !validation.Valid {
					// One bounded fallback: shift this request to next feasible start on same machine.
					// This addresses residual overlaps that can appear after per-proposal repair.
					if len(validation.Reasons) > 0 {
						reasonLower := strings.ToLower(validation.Reasons[0])
						if strings.Contains(reasonLower, "overlapping") ||
							strings.Contains(reasonLower, "outside") ||
							strings.Contains(reasonLower, "calendar") ||
							strings.Contains(reasonLower, "previous process step completes") {
							processStep, psErr := s.scheduling.GetProcessStepForJobStep(jobStepID)
							if psErr == nil && processStep != nil {
								activeRowsNow, arErr := txSlotRepo.ListActiveByJobIDs(nil)
								if arErr == nil {
									busyNow := tentativeSlotsFromActiveRows(activeRowsNow, map[string]bool{record.JobID: true})
									tryStart := start
									if previousEnd != nil && previousEnd.After(tryStart) {
										tryStart = *previousEnd
									}
									repairedStart, ok, _, _ := s.scheduling.findFeasibleMachineStart(
										jobStepID,
										rs.MachineID,
										processStep,
										tryStart,
										time.Duration(rs.DurationMins)*time.Minute,
										maxInt(rs.Quantity, 1),
										"",
										busyNow,
										func() *time.Time {
											if previousEnd != nil && chainPrevEnd != nil {
												if previousEnd.After(*chainPrevEnd) {
													return previousEnd
												}
												return chainPrevEnd
											}
											if previousEnd != nil {
												return previousEnd
											}
											return chainPrevEnd
										}(),
										alignSuccessorStart(time.Now().UTC().Add(time.Duration(maxHorizonDays)*24*time.Hour)),
									)
									if !ok {
									}
									if ok {
										repairedEnd := repairedStart.Add(time.Duration(rs.DurationMins) * time.Minute)
										recheck, reErr := txScheduling.ValidateSlotWithOptions(jobStepID, rs.MachineID, repairedStart, repairedEnd, rs.Quantity, "", SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitQty})
										if reErr != nil || !recheck.Valid {
											// Secondary bounded fallback: authoritative incremental scan using tx validator.
											scanStart := alignSuccessorStart(start.Add(30 * time.Minute))
											scanCap := alignSuccessorStart(time.Now().UTC().Add(time.Duration(maxHorizonDays) * 24 * time.Hour))
											for scanSteps := 0; scanSteps < 4096 && !scanStart.After(scanCap); scanSteps++ {
												scanEnd := scanStart.Add(time.Duration(rs.DurationMins) * time.Minute)
												scanCheck, scanErr := txScheduling.ValidateSlotWithOptions(jobStepID, rs.MachineID, scanStart, scanEnd, rs.Quantity, "", SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitQty})
												if scanErr == nil && scanCheck.Valid {
													repairedStart = scanStart
													repairedEnd = scanEnd
													recheck = scanCheck
													reErr = nil
													break
												}
												scanStart = alignSuccessorStart(scanStart.Add(30 * time.Minute))
											}
										}
										if reErr == nil && recheck.Valid {
											start = repairedStart
											end = repairedEnd
											rs.StartTime = repairedStart.Format(time.RFC3339)
											validation = recheck
										}
									}
								}
							}
						}
					}
				}
				if !validation.Valid {
					if len(validation.Reasons) > 0 && strings.Contains(strings.ToLower(validation.Reasons[0]), "outside resource work calendar") {
						return newSchedulingActionError(
							422,
							fmt.Sprintf(
								"slot is outside resource work calendar (job_step_id=%s, machine_id=%s, start=%s, end=%s). Refresh work calendars and regenerate proposals before apply",
								jobStepID,
								rs.MachineID,
								start.UTC().Format(time.RFC3339),
								end.UTC().Format(time.RFC3339),
							),
						)
					}
					return newSchedulingActionError(422, strings.Join(validation.Reasons, "; "))
				}
				prev := end
				previousEnd = &prev
				if end.After(stepMaxEnd) {
					stepMaxEnd = end
				}
			}
			if !stepMaxEnd.IsZero() {
				next := stepMaxEnd
				chainPrevEnd = &next
			}
			created, err := txSlotService.SplitStep(jobStepID, grouped[jobStepID])
			if err != nil {
				return err
			}
			for _, slot := range created {
				slot.ProposalID = record.ProposalID
				if err := txSlotRepo.Update(&slot); err != nil {
					return err
				}
				createdIDs = append(createdIDs, slot.SlotID)
			}
		}
		now := time.Now().UTC()
		record.Status = domain.AIProposalStatusApplied
		record.AppliedBy = defaultActor(appliedBy)
		record.IdempotencyKey = strings.TrimSpace(idempotencyKey)
		record.AppliedAt = &now
		record.OutcomeStatus = "awaiting_execution"
		record.UpdatedAt = now
		return repository.NewAIProposalRepository(tx).Update(record)
	}
	applyErr := s.db.Transaction(applyFn)
	if applyErr != nil {
		if s.metrics != nil {
			s.metrics.Inc(&s.metrics.ProposalApplyFailures)
		}
		return nil, applyErr
	}
	if s.metrics != nil {
		s.metrics.Inc(&s.metrics.ProposalApplied)
	}
	logger.L().Info("ai_proposal_applied",
		zap.String("proposal_id", proposalID),
		zap.String("job_id", record.JobID),
		zap.String("applied_by", defaultActor(appliedBy)),
		zap.String("idempotency_key", idempotencyKey),
	)
	return &AppliedProposalResult{
		ProposalID:             record.ProposalID,
		JobID:                  record.JobID,
		AppliedAt:              derefTime(record.AppliedAt),
		AppliedSlotCount:       len(createdIDs),
		CreatedSlots:           createdIDs,
		CreatedJobIDs:          createdJobIDs,
		CreatedDependencyLinks: createdDependencyLinks,
		Message:                "Proposal applied successfully. Review created slots before dispatch.",
		IdempotencyKey:         idempotencyKey,
		Proposal:               proposal,
	}, nil
}

func normalizeLegacySplitFallbackSlots(slots []ProposedSlot, stepRepo *repository.JobStepRepository, processRepo *repository.ProcessRepository) ([]ProposedSlot, error) {
	if len(slots) == 0 {
		return nil, nil
	}
	out := append([]ProposedSlot(nil), slots...)
	indexByStep := make(map[string][]int)
	for i := range out {
		indexByStep[out[i].JobStepID] = append(indexByStep[out[i].JobStepID], i)
	}
	for jobStepID, indexes := range indexByStep {
		if len(indexes) <= 1 {
			continue
		}
		sort.Slice(indexes, func(i, j int) bool {
			a := out[indexes[i]]
			b := out[indexes[j]]
			if a.ScheduledStart.Equal(b.ScheduledStart) {
				return a.ScheduledEnd.Before(b.ScheduledEnd)
			}
			return a.ScheduledStart.Before(b.ScheduledStart)
		})
		jobStep, err := stepRepo.GetByID(jobStepID)
		if err != nil {
			return nil, err
		}
		totalPlanned := 0
		allSlicesUseFullTarget := true
		allSlicesSequential := true
		slices := make([]BusyInterval, 0, len(indexes))
		for _, idx := range indexes {
			slot := out[idx]
			totalPlanned += slot.QuantityPlanned
			if slot.QuantityPlanned != jobStep.QuantityTarget {
				allSlicesUseFullTarget = false
			}
			if slot.IsParallel {
				allSlicesSequential = false
			}
			slices = append(slices, BusyInterval{Start: slot.ScheduledStart, End: slot.ScheduledEnd})
		}
		if totalPlanned == jobStep.QuantityTarget {
			continue
		}
		if !allSlicesUseFullTarget || !allSlicesSequential {
			return nil, newSchedulingActionError(422, fmt.Sprintf("proposal step %s has invalid split quantities; regenerate the proposal before apply", jobStepID))
		}
		if _, err := processRepo.GetStepByID(jobStep.StepID); err != nil {
			return nil, err
		}
		allocations := allocateSplitSliceQuantities(jobStep.QuantityTarget, slices)
		if len(allocations) != len(indexes) {
			return nil, newSchedulingActionError(422, fmt.Sprintf("proposal step %s has invalid legacy split quantities and cannot be auto-repaired; regenerate the proposal before apply", jobStepID))
		}
		alignedSlices := normalizeLegacySequentialSlices(indexes, out)
		for i, idx := range indexes {
			out[idx].QuantityPlanned = allocations[i]
			out[idx].AllocationPercent = mathRound(float64(allocations[i])*100/float64(jobStep.QuantityTarget), 2)
			out[idx].ScheduledStart = alignedSlices[i].ScheduledStart
			out[idx].ScheduledEnd = alignedSlices[i].ScheduledEnd
			if out[idx].ScheduledEnd.After(out[idx].ScheduledStart) {
				out[idx].EstimatedDurationMins = int(out[idx].ScheduledEnd.Sub(out[idx].ScheduledStart).Minutes())
			}
		}
	}
	return out, nil
}

func normalizeLegacySequentialSlices(indexes []int, slots []ProposedSlot) []ProposedSlot {
	normalized := make([]ProposedSlot, len(indexes))
	if len(indexes) == 0 {
		return normalized
	}
	cursor := roundUpToHalfHour(slots[indexes[0]].ScheduledStart)
	if cursor.IsZero() {
		cursor = slots[indexes[0]].ScheduledStart
	}
	for i, idx := range indexes {
		slot := slots[idx]
		duration := slot.ScheduledEnd.Sub(slot.ScheduledStart)
		if slot.EstimatedDurationMins > 0 {
			duration = time.Duration(slot.EstimatedDurationMins) * time.Minute
		}
		if duration <= 0 {
			duration = schedulerSlotGranularity
		}
		duration = ceilDurationTo30Min(duration)
		slot.ScheduledStart = cursor
		slot.ScheduledEnd = cursor.Add(duration)
		slot.EstimatedDurationMins = int(duration / time.Minute)
		normalized[i] = slot
		cursor = slot.ScheduledEnd
	}
	return normalized
}

func (s *AIPredictiveService) ensureProposalFresh(record *domain.AIProposal) error {
	if record == nil {
		return newSchedulingActionError(404, "proposal not found")
	}
	current, err := s.BuildProposalWithOptions(record.JobID, true)
	if err != nil {
		return newSchedulingActionError(500, fmt.Sprintf("freshness check failed during schedule rebuild for job %s: %s", record.JobID, err.Error()))
	}
	currentHash := ""
	if current != nil {
		currentHash = current.SnapshotHash
	}
	if currentHash == record.InputHash {
		return nil
	}
	now := time.Now().UTC()
	record.Status = domain.AIProposalStatusStale
	record.StaleDetectedAt = &now
	record.UpdatedAt = now
	_ = s.proposalRepo.Update(record)
	if s.metrics != nil {
		s.metrics.Inc(&s.metrics.ProposalStale)
	}
	return newSchedulingActionError(409, "proposal is stale (error_code=proposal_stale) and must be regenerated. For Apply All, send skip_staleness_check=true on approve/apply requests; otherwise regenerate via Reschedule All")
}

func (s *AIPredictiveService) decodeProposalRecord(record *domain.AIProposal) (*SchedulingProposal, error) {
	if record == nil {
		return nil, gorm.ErrRecordNotFound
	}
	proposal, feasiblePresent, err := decodeSchedulingProposalJSON(record.ProposalJSON)
	if err != nil {
		return nil, err
	}
	if !feasiblePresent {
		// Backward compatibility: older records may omit "feasible"; infer
		// deterministic default from blocked reasons to avoid false apply rejects.
		inferredFeasible := len(proposal.BlockedReasons) == 0
		proposal.Feasible = inferredFeasible
		logger.L().Warn("proposal_missing_feasible_field_inferred",
			zap.String("proposal_id", record.ProposalID),
			zap.Bool("inferred_feasible", inferredFeasible),
		)
	}
	proposal.ProposalID = record.ProposalID
	proposal.Version = record.Version
	proposal.Status = record.Status
	proposal.RolloutState = record.RolloutState
	proposal.ShadowEngine = record.ShadowEngine
	proposal.ShadowObjectiveScore = record.ShadowObjectiveScore
	proposal.Engine = record.Engine
	proposal.EngineVersion = record.EngineVersion
	proposal.ObjectiveScore = record.ObjectiveScore
	proposal.FallbackReason = record.FallbackReason
	proposal.SnapshotHash = record.InputHash
	normalizeFeasibleDependentJobPlans(proposal)
	return proposal, nil
}

func decodeSchedulingProposalJSON(raw string) (*SchedulingProposal, bool, error) {
	var proposal SchedulingProposal
	if err := json.Unmarshal([]byte(raw), &proposal); err != nil {
		return nil, false, err
	}
	var probe struct {
		Feasible *bool `json:"feasible"`
	}
	if err := json.Unmarshal([]byte(raw), &probe); err != nil {
		return nil, false, err
	}
	return &proposal, probe.Feasible != nil, nil
}

func mustJSON(v interface{}) string {
	raw, _ := json.Marshal(v)
	return string(raw)
}

func defaultActor(actor string) string {
	actor = strings.TrimSpace(actor)
	if actor == "" {
		return "system"
	}
	return actor
}

func derefTime(v *time.Time) time.Time {
	if v == nil {
		return time.Time{}
	}
	return *v
}
