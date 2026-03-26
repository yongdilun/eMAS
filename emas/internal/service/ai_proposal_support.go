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
	Job           proposalSnapshotJob     `json:"job"`
	Preview       proposalSnapshotPreview `json:"preview"`
	ExistingSlots []proposalSnapshotSlot  `json:"existing_slots"`

	// MachineIDs defines the fixed ordering for all vector features.
	MachineIDs []string `json:"machine_ids"`

	QueueLengthsVector       []int     `json:"queue_lengths_vector"`
	MachineUtilizationVector []float64 `json:"machine_utilization_vector"`
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
	return proposal, nil
}

func (s *AIPredictiveService) buildProposalForPreview(job *domain.Job, preview *SolverPreview, tentativeSlots []TentativeSlot, targetCompletion *time.Time) (*SchedulingProposal, error) {
	mode := s.primaryEngineMode()
	proposal, err := s.buildWithEngine(job, preview, mode, tentativeSlots, targetCompletion)
	if err == nil {
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
			cp.ProposedSlots[i].ScheduledStart = cp.ProposedSlots[i].ScheduledStart.Add(delta)
			cp.ProposedSlots[i].ScheduledEnd = cp.ProposedSlots[i].ScheduledEnd.Add(delta)
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
		p, err := st.Generate(ctx, s, job, preview, tentativeSlots, targetCompletion)
		cancel()
		if err != nil || p == nil {
			continue
		}

		// Variant A: as-is strategy result
		addCandidate(p, st.ID(), fmt.Sprintf("%s/A", st.ID()), "base")

		// Variant B: second-best (only defined for earliest-finish right now)
		if st.ID() == "greedy_earliest_finish" {
			ctx2, cancel2 := context.WithTimeout(context.Background(), perStrategy)
			p2, _ := GreedySecondBestFinish{}.Generate(ctx2, s, job, preview, tentativeSlots, targetCompletion)
			cancel2()
			addCandidate(p2, "greedy_second_best_finish", fmt.Sprintf("%s/B", st.ID()), "second_best")
		}

		// Variant C: small what-if time shift (+5m)
		addCandidate(shiftedClone(p, 5*time.Minute, "shift_plus_5m"), st.ID(), fmt.Sprintf("%s/C", st.ID()), "shift_plus_5m")

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
		p, _ := GreedyEarliestFinish{}.Generate(ctx, s, job, preview, tentativeSlots, targetCompletion)
		if p == nil {
			return nil, fmt.Errorf("failed to generate heuristic proposal")
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
		EarliestStart:  time.Now(),
		ProposedSlots:  make([]ProposedSlot, 0),
		Summary:        make([]string, 0, 4),
		BlockedReasons: make([]string, 0, 4),
	}
	cursor := time.Now()
	if preview.EarliestReadyAt != nil && preview.EarliestReadyAt.After(cursor) {
		cursor = *preview.EarliestReadyAt
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
		duration := estimatedStepDuration(domain.ProcessSteps{
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
			end := start.Add(duration)
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
				EstimatedDurationMins: int(duration.Minutes()),
				Reasoning: []string{
					"Preview optimizer selected the machine combination with the earliest projected completion.",
					fmt.Sprintf("Machine %s was chosen because it minimizes finish time under current readiness and availability.", candidate.MachineName),
				},
			})
		}
		proposal.Summary = append(proposal.Summary, fmt.Sprintf("Optimizer scheduled step %s using %d machine(s).", step.StepName, parallelCount))
		cursor = stepEnd
		cursor = cursor.Add(time.Duration(step.MinWaitMinutes+step.TransferMinutes) * time.Minute)
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
func (s *AIPredictiveService) buildProposalSnapshotWithTentative(jobID string, tentativeSlots []TentativeSlot) (*SolverPreview, string, string, error) {
	job, err := s.jobRepo.GetByID(jobID)
	if err != nil {
		return nil, "", "", err
	}
	preview, err := s.scheduling.BuildSolverPreviewWithTentativeSlots(jobID, tentativeSlots)
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
		ProposalJSON:         mustJSON(proposal),
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
	if s.metrics != nil {
		s.metrics.Inc(&s.metrics.ProposalGenerated)
	}
	logger.L().Info("ai_proposal_generated",
		zap.String("proposal_id", proposalID),
		zap.String("job_id", jobID),
		zap.String("engine", proposal.Engine),
		zap.String("generated_by", defaultActor(generatedBy)),
	)
	return proposal, nil
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
	applyFn := func(tx *gorm.DB) error {
		txSlotRepo := repository.NewJobSlotRepository(tx)
		txStepRepo := repository.NewJobStepRepository(tx)
		txJobRepo := repository.NewJobRepository(tx)
		txProcessRepo := repository.NewProcessRepository(tx)
		txScheduling := s.scheduling.WithSlotRepo(txSlotRepo)
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
		normalizedSlots, err := normalizeLegacySplitFallbackSlots(proposal.ProposedSlots, txStepRepo, txProcessRepo)
		if err != nil {
			return err
		}
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
		for _, jobStepID := range order {
			ignoreMinSplitQty := isTemporalSliceRequestGroup(grouped[jobStepID])
			// Pre-validate each proposed slot so we can return a precise, actionable
			// error message instead of a generic validation string.
			for _, rs := range grouped[jobStepID] {
				start, parseErr := time.Parse(time.RFC3339, rs.StartTime)
				if parseErr != nil {
					return newSchedulingActionError(422, "invalid proposed slot start time: "+rs.StartTime)
				}
				end := start.Add(time.Duration(rs.DurationMins) * time.Minute)
				validation, vErr := txScheduling.ValidateSlotWithOptions(jobStepID, rs.MachineID, start, end, rs.Quantity, "", SlotValidationOptions{IgnoreMinSplitQty: ignoreMinSplitQty})
				if vErr != nil {
					return vErr
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
		ProposalID:       record.ProposalID,
		JobID:            record.JobID,
		AppliedAt:        derefTime(record.AppliedAt),
		AppliedSlotCount: len(createdIDs),
		CreatedSlots:     createdIDs,
		Message:          "Proposal applied successfully. Review created slots before dispatch.",
		IdempotencyKey:   idempotencyKey,
		Proposal:         proposal,
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
		for i, idx := range indexes {
			out[idx].QuantityPlanned = allocations[i]
			out[idx].AllocationPercent = mathRound(float64(allocations[i])*100/float64(jobStep.QuantityTarget), 2)
		}
	}
	return out, nil
}

func (s *AIPredictiveService) ensureProposalFresh(record *domain.AIProposal) error {
	if record == nil {
		return newSchedulingActionError(404, "proposal not found")
	}
	_, _, currentHash, err := s.buildProposalSnapshot(record.JobID)
	if err != nil {
		return err
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
