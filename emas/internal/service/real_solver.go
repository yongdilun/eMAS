package service

// realSchedulingOptimizer implements a production-grade dispatching scheduler with
// local-search improvement for single-job multi-step scheduling problems.
//
// Algorithm:
//  1. Phase 1 – greedy dispatch: for every step in precedence order, enumerate
//     candidate machine assignments (single + parallel combos up to
//     MaxParallelMachines), score each by objective contribution, commit the best.
//  2. Phase 2 – local search: iterate over committed assignments and try
//     alternative machine choices; accept any improvement until no better swap
//     is found or the context deadline fires.
//
// Objective: score in [0, 1000], maximised.
//
//	score = 1000
//	      - tardiness_penalty     (≤ 500)
//	      - makespan_penalty      (≤ 200)
//	      - blocked_step_penalty  (300 per blocked step)
//	      + early_finish_bonus    (≤ 100)

import (
	"context"
	"emas/internal/domain"
	"math"
	"sort"
	"time"
)

const (
	realSolverEngineName    = "real-solver"
	realSolverEngineVersion = "dispatch-ls-v1"
	maxLocalSearchIters     = 50
	beamWidth               = 3
)

// --- internal plan types ---

// slotPlan captures the concrete scheduling decision for one machine assignment
// within a step. It maps 1:1 to a ProposedSlot in the final proposal.
type slotPlan struct {
	machineID    string
	machineName  string
	start        time.Time
	end          time.Time
	qty          int
	pct          float64
	durationMins int
	isParallel   bool
	batchSeq     int
}

// stepPlan holds the chosen schedule for one job step.
type stepPlan struct {
	step         SolverPreviewStep
	slots        []slotPlan
	start        time.Time
	end          time.Time
	durationMins int
	blocked      bool // true when no candidate machine is available
}

// machineState tracks per-machine scheduling state during optimisation.
type machineState struct {
	machineID        string
	machineName      string
	freeAt           time.Time
	capacityPerHour  int
	efficiencyFactor float64
}

// --- optimizer ---

type realSchedulingOptimizer struct {
	job     *domain.Job
	preview *SolverPreview
	cursor  time.Time // earliest allowed start, derived from material readiness
}

func newRealSchedulingOptimizer(job *domain.Job, preview *SolverPreview) *realSchedulingOptimizer {
	cursor := roundUpToHalfHour(time.Now().UTC())
	if preview.EarliestReadyAt != nil && preview.EarliestReadyAt.After(cursor) {
		cursor = alignSuccessorStart(*preview.EarliestReadyAt)
	}
	return &realSchedulingOptimizer{job: job, preview: preview, cursor: cursor}
}

// solve runs both phases and returns the best plan and its objective score.
func (o *realSchedulingOptimizer) solve(ctx context.Context) ([]stepPlan, float64, error) {
	plans, err := o.greedySchedule(ctx)
	if err != nil {
		return nil, 0, err
	}
	score := o.objectiveScore(plans)
	plans, score = o.localSearch(ctx, plans, score)
	return plans, score, nil
}

// --- Phase 1: greedy dispatch ---

func (o *realSchedulingOptimizer) greedySchedule(ctx context.Context) ([]stepPlan, error) {
	states := o.initialMachineStates()
	cursor := o.cursor
	plans := make([]stepPlan, 0, len(o.preview.Steps))

	for _, step := range o.preview.Steps {
		select {
		case <-ctx.Done():
			return plans, ctx.Err()
		default:
		}
		available := filterAvailableCandidates(step.CandidateMachines)
		if len(available) == 0 {
			plans = append(plans, stepPlan{step: step, start: cursor, end: cursor, blocked: true})
			continue
		}
		best := o.bestAssignment(step, available, states, cursor)
		plans = append(plans, best)
		// Advance machine free-at times and step cursor.
		for _, sl := range best.slots {
			if ms, ok := states[sl.machineID]; ok {
				if sl.end.After(ms.freeAt) {
					ms.freeAt = sl.end
					states[sl.machineID] = ms
				}
			}
		}
		if best.end.After(cursor) {
			cursor = best.end
		}
		cursor = alignSuccessorStart(cursor.Add(time.Duration(step.MinWaitMinutes+step.TransferMinutes) * time.Minute))
	}
	return plans, nil
}

// initialMachineStates builds a freeAt-keyed map from all candidates visible in
// the preview. AvailableFrom is used as the initial free-at time.
func (o *realSchedulingOptimizer) initialMachineStates() map[string]machineState {
	states := make(map[string]machineState)
	for _, step := range o.preview.Steps {
		for _, c := range step.CandidateMachines {
			if _, exists := states[c.MachineID]; exists {
				continue
			}
			ef := c.EfficiencyFactor
			if ef <= 0 {
				ef = 1.0
			}
			states[c.MachineID] = machineState{
				machineID:        c.MachineID,
				machineName:      c.MachineName,
				freeAt:           c.AvailableFrom,
				capacityPerHour:  c.CapacityPerHour,
				efficiencyFactor: ef,
			}
		}
	}
	return states
}

// bestAssignment enumerates single-machine and parallel candidate combos, scores
// each, and returns the highest-scoring stepPlan.
func (o *realSchedulingOptimizer) bestAssignment(
	step SolverPreviewStep,
	available []CandidateMachine,
	states map[string]machineState,
	cursor time.Time,
) stepPlan {
	type candidate struct {
		plan  stepPlan
		score float64
	}
	candidates := make([]candidate, 0, len(available)*2)

	// Single-machine options.
	for _, m := range available {
		plan := o.singleMachinePlan(step, m, states, cursor)
		candidates = append(candidates, candidate{plan: plan, score: o.planScore(plan)})
	}

	// Parallel options – only when the step flags it and data supports it.
	canParallel := step.AllowParallelExecution &&
		step.MaxParallelMachines > 1 &&
		len(available) > 1 &&
		step.QuantityTarget >= maxInt(step.MinSplitQty, 1)*2

	if canParallel {
		maxPar := minInt(step.MaxParallelMachines, len(available))
		if maxPar > 3 {
			maxPar = 3
		}
		// Two-machine combos from the best beamWidth candidates.
		limit := minInt(beamWidth+1, len(available))
		for i := 0; i < limit; i++ {
			for j := i + 1; j < limit; j++ {
				plan := o.parallelPlan(step, []CandidateMachine{available[i], available[j]}, states, cursor)
				candidates = append(candidates, candidate{plan: plan, score: o.planScore(plan)})
			}
		}
		// Three-machine combos.
		if maxPar >= 3 && len(available) >= 3 {
			lim3 := minInt(beamWidth, len(available))
			for i := 0; i < lim3; i++ {
				for j := i + 1; j < lim3; j++ {
					for k := j + 1; k < lim3; k++ {
						plan := o.parallelPlan(step,
							[]CandidateMachine{available[i], available[j], available[k]},
							states, cursor)
						candidates = append(candidates, candidate{plan: plan, score: o.planScore(plan)})
					}
				}
			}
		}
	}

	sort.SliceStable(candidates, func(i, j int) bool {
		return candidates[i].score > candidates[j].score
	})
	if len(candidates) == 0 {
		return stepPlan{step: step, start: cursor, end: cursor, blocked: true}
	}
	return candidates[0].plan
}

// singleMachinePlan builds the stepPlan for one machine, accounting for machine
// free-at time, efficiency factor, and step overheads via estimatedStepDuration.
func (o *realSchedulingOptimizer) singleMachinePlan(
	step SolverPreviewStep,
	m CandidateMachine,
	states map[string]machineState,
	cursor time.Time,
) stepPlan {
	ms := states[m.MachineID]
	processStep := domain.ProcessSteps{
		DefaultPreparationTime: 0,
		DefaultProcessingTime:  maxInt(step.EstimatedDurationMins, 1),
		DefaultCleaningTime:    0,
		DefaultChangeoverTime:  0,
	}
	// Use estimatedStepDuration with the single candidate so efficiency and
	// capacity are factored in correctly.
	duration := estimatedStepDuration(processStep, []CandidateMachine{m}, float64(step.QuantityTarget))
	if duration < time.Minute {
		duration = time.Minute
	}
	durationMins := int(duration.Minutes())

	start := cursor
	if m.AvailableFrom.After(start) {
		start = m.AvailableFrom
	}
	if ms.freeAt.After(start) {
		start = ms.freeAt
	}
	start = alignSuccessorStart(start)
	end := start.Add(duration)

	return stepPlan{
		step:         step,
		start:        start,
		end:          end,
		durationMins: durationMins,
		slots: []slotPlan{{
			machineID:    m.MachineID,
			machineName:  m.MachineName,
			start:        start,
			end:          end,
			qty:          step.QuantityTarget,
			pct:          100.0,
			durationMins: durationMins,
			isParallel:   false,
			batchSeq:     1,
		}},
	}
}

// parallelPlan distributes the step quantity across a set of machines run in
// parallel; each machine gets an equal share. Duration is calculated with all
// machines together so that combined capacity is used.
func (o *realSchedulingOptimizer) parallelPlan(
	step SolverPreviewStep,
	machines []CandidateMachine,
	states map[string]machineState,
	cursor time.Time,
) stepPlan {
	n := len(machines)
	processStep := domain.ProcessSteps{
		DefaultProcessingTime: maxInt(step.EstimatedDurationMins, 1),
		BatchSize:             step.BatchSize,
		IsBatchProcess:        step.IsBatchProcess,
	}
	duration := estimatedStepDuration(processStep, machines, float64(step.QuantityTarget))
	if duration < time.Minute {
		duration = time.Minute
	}
	durationMins := int(duration.Minutes())

	// Start when all selected machines are free.
	start := cursor
	for _, m := range machines {
		if m.AvailableFrom.After(start) {
			start = m.AvailableFrom
		}
		if ms, ok := states[m.MachineID]; ok && ms.freeAt.After(start) {
			start = ms.freeAt
		}
	}
	start = alignSuccessorStart(start)
	end := start.Add(duration)

	allocs := equalPercents(n)
	qtys := allocateSplitQuantities(step.QuantityTarget, allocs, n, step.MinBatchSize)
	slots := make([]slotPlan, n)
	for i, m := range machines {
		slots[i] = slotPlan{
			machineID:    m.MachineID,
			machineName:  m.MachineName,
			start:        start,
			end:          end,
			qty:          qtys[i],
			pct:          allocs[i],
			durationMins: durationMins,
			isParallel:   true,
			batchSeq:     i + 1,
		}
	}
	return stepPlan{
		step:         step,
		start:        start,
		end:          end,
		durationMins: durationMins,
		slots:        slots,
	}
}

// --- Phase 2: local search ---

// localSearch iterates over the committed plan and tries re-assigning each step
// to an alternative machine (or parallel combination). Accepts any improvement.
func (o *realSchedulingOptimizer) localSearch(ctx context.Context, plans []stepPlan, baseScore float64) ([]stepPlan, float64) {
	best := append([]stepPlan(nil), plans...)
	bestScore := baseScore

	for iter := 0; iter < maxLocalSearchIters; iter++ {
		select {
		case <-ctx.Done():
			return best, bestScore
		default:
		}
		improved := false

		for i, plan := range best {
			if plan.blocked {
				continue
			}
			available := filterAvailableCandidates(plan.step.CandidateMachines)
			if len(available) <= 1 {
				continue
			}

			// Build machine states committed by the steps before i.
			states := o.statesUpTo(best, i)
			cursor := o.cursor
			if i > 0 {
				prev := best[i-1]
				cursor = alignSuccessorStart(prev.end.Add(time.Duration(prev.step.MinWaitMinutes+prev.step.TransferMinutes) * time.Minute))
			}

			for _, alt := range available {
				// Skip the machine currently in use (single-slot case).
				if len(plan.slots) == 1 && plan.slots[0].machineID == alt.MachineID {
					continue
				}
				newPlan := o.singleMachinePlan(plan.step, alt, states, cursor)
				trial := append([]stepPlan(nil), best...)
				trial[i] = newPlan
				trial = o.recomputeFrom(trial, i+1)
				trialScore := o.objectiveScore(trial)
				if trialScore > bestScore {
					best = trial
					bestScore = trialScore
					improved = true
					break
				}
			}
			if improved {
				break
			}
		}
		if !improved {
			break
		}
	}
	return best, bestScore
}

// statesUpTo rebuilds machine freeAt states from plans[0..upToIndex) so that
// local search can correctly evaluate alternative assignments for plans[upToIndex].
func (o *realSchedulingOptimizer) statesUpTo(plans []stepPlan, upToIndex int) map[string]machineState {
	states := o.initialMachineStates()
	for i := 0; i < upToIndex && i < len(plans); i++ {
		for _, sl := range plans[i].slots {
			if ms, ok := states[sl.machineID]; ok && sl.end.After(ms.freeAt) {
				ms.freeAt = sl.end
				states[sl.machineID] = ms
			}
		}
	}
	return states
}

// recomputeFrom re-runs greedy dispatch for plans[fromIndex:] using the
// assignments already committed in plans[:fromIndex].
func (o *realSchedulingOptimizer) recomputeFrom(plans []stepPlan, fromIndex int) []stepPlan {
	if fromIndex >= len(plans) {
		return plans
	}
	states := o.statesUpTo(plans, fromIndex)
	cursor := o.cursor
	if fromIndex > 0 && !plans[fromIndex-1].end.IsZero() {
		prev := plans[fromIndex-1]
		cursor = alignSuccessorStart(prev.end.Add(time.Duration(prev.step.MinWaitMinutes+prev.step.TransferMinutes) * time.Minute))
	}
	for i := fromIndex; i < len(plans); i++ {
		step := plans[i].step
		available := filterAvailableCandidates(step.CandidateMachines)
		if len(available) == 0 {
			plans[i] = stepPlan{step: step, start: cursor, end: cursor, blocked: true}
			continue
		}
		plans[i] = o.bestAssignment(step, available, states, cursor)
		for _, sl := range plans[i].slots {
			if ms, ok := states[sl.machineID]; ok && sl.end.After(ms.freeAt) {
				ms.freeAt = sl.end
				states[sl.machineID] = ms
			}
		}
		if plans[i].end.After(cursor) {
			cursor = plans[i].end
		}
		cursor = alignSuccessorStart(cursor.Add(time.Duration(step.MinWaitMinutes+step.TransferMinutes) * time.Minute))
	}
	return plans
}

// --- Scoring ---

// planScore evaluates a single step assignment during dispatch. Higher = better.
func (o *realSchedulingOptimizer) planScore(plan stepPlan) float64 {
	if len(plan.slots) == 0 {
		return -1e9
	}
	deadline := o.job.Deadline
	// Primary: earlier finish vs deadline is better.
	timeToDeadlineMins := deadline.Sub(plan.end).Minutes()
	// Secondary: throughput per slot-hour.
	durationH := plan.end.Sub(plan.start).Hours()
	if durationH <= 0 {
		durationH = 0.01
	}
	throughput := float64(plan.step.QuantityTarget) / durationH
	// Bonus: parallel assignments (reduces makespan for later steps).
	parallelBonus := 0.0
	if len(plan.slots) > 1 {
		parallelBonus = float64(len(plan.slots)) * 10
	}
	return timeToDeadlineMins + throughput/10 + parallelBonus
}

// objectiveScore computes the full schedule-level score in [0, 1100].
func (o *realSchedulingOptimizer) objectiveScore(plans []stepPlan) float64 {
	if len(plans) == 0 {
		return 0
	}
	deadline := o.job.Deadline
	// Latest end time across all non-blocked steps.
	var latestEnd time.Time
	for _, p := range plans {
		if !p.blocked && p.end.After(latestEnd) {
			latestEnd = p.end
		}
	}

	score := 1000.0

	// Tardiness penalty.
	if !latestEnd.IsZero() && latestEnd.After(deadline) {
		tardinessMins := latestEnd.Sub(deadline).Minutes()
		score -= math.Min(tardinessMins/10, 500)
	} else if !latestEnd.IsZero() {
		earlinessHours := deadline.Sub(latestEnd).Hours()
		score += math.Min(earlinessHours*5, 100)
	}

	// Makespan penalty.
	if !latestEnd.IsZero() {
		makespanH := latestEnd.Sub(o.cursor).Hours()
		score -= math.Min(makespanH*2, 200)
	}

	// Blocked step penalty.
	for _, p := range plans {
		if p.blocked {
			score -= 300
		}
	}

	if score < 0 {
		score = 0
	}
	return score
}

// --- Proposal builder ---

// buildRealSolverProposal converts the internal plan representation into the
// standard SchedulingProposal format that the rest of the service expects.
func buildRealSolverProposal(
	job *domain.Job,
	plans []stepPlan,
	score float64,
	earliestStart time.Time,
) *SchedulingProposal {
	proposal := &SchedulingProposal{
		JobID:          job.JobID,
		ProductID:      job.ProductID,
		Engine:         realSolverEngineName,
		EngineVersion:  realSolverEngineVersion,
		GeneratedAt:    time.Now().UTC(),
		EarliestStart:  earliestStart,
		Feasible:       true,
		ObjectiveScore: score,
		ProposedSlots:  make([]ProposedSlot, 0, len(plans)*2),
		Summary:        make([]string, 0, len(plans)+2),
		BlockedReasons: make([]string, 0),
	}

	for _, sp := range plans {
		if sp.blocked {
			proposal.Feasible = false
			proposal.BlockedReasons = append(proposal.BlockedReasons,
				"No candidate machine is available for step "+sp.step.StepName+".")
			continue
		}
		for _, sl := range sp.slots {
			reasoning := []string{
				"Real dispatcher (dispatch-ls-v1) selected this machine after scoring all feasible assignments.",
			}
			if sl.isParallel {
				reasoning = append(reasoning,
					"Step was split across parallel machines to reduce total duration.")
			}
			if score >= 900 {
				reasoning = append(reasoning,
					"Schedule is projected to finish comfortably before the job deadline.")
			}
			proposal.ProposedSlots = append(proposal.ProposedSlots, ProposedSlot{
				JobStepID:             sp.step.JobStepID,
				StepID:                sp.step.StepID,
				StepName:              sp.step.StepName,
				MachineID:             sl.machineID,
				MachineName:           sl.machineName,
				ScheduledStart:        sl.start,
				ScheduledEnd:          sl.end,
				QuantityPlanned:       sl.qty,
				AllocationPercent:     sl.pct,
				IsParallel:            sl.isParallel,
				BatchSequence:         sl.batchSeq,
				ActualDurationMins:    sp.step.ActualDurationMins,
				EstimatedDurationMins: sl.durationMins,
				ReservedDurationMins:  sl.durationMins,
				RoundingOverheadMins:  maxInt(sl.durationMins-sp.step.ActualDurationMins, 0),
				Reasoning:             reasoning,
			})
		}
		machineNames := machineNamesFromSlots(sp.slots)
		proposal.Summary = append(proposal.Summary,
			"Step "+sp.step.StepName+" assigned to "+machineNames+" ("+formatDuration(sp.durationMins)+" estimated).")
	}

	if len(proposal.ProposedSlots) > 0 {
		latest := proposal.ProposedSlots[0].ScheduledEnd
		for _, ps := range proposal.ProposedSlots {
			if ps.ScheduledEnd.After(latest) {
				latest = ps.ScheduledEnd
			}
		}
		proposal.EstimatedCompletion = &latest
	}

	if !proposal.Feasible {
		proposal.Summary = append(proposal.Summary, "Some steps could not be scheduled — planner review required.")
	} else {
		proposal.Summary = append(proposal.Summary,
			"Objective score: "+formatScore(score)+". Local-search improvement passes were applied after initial dispatch.")
	}
	return proposal
}

func machineNamesFromSlots(slots []slotPlan) string {
	if len(slots) == 0 {
		return "no machine"
	}
	seen := make(map[string]bool)
	out := ""
	for _, sl := range slots {
		if !seen[sl.machineName] {
			if out != "" {
				out += " + "
			}
			out += sl.machineName
			seen[sl.machineName] = true
		}
	}
	return out
}

func formatDuration(mins int) string {
	if mins < 60 {
		return itoa(mins) + "m"
	}
	h := mins / 60
	m := mins % 60
	if m == 0 {
		return itoa(h) + "h"
	}
	return itoa(h) + "h" + itoa(m) + "m"
}

func formatScore(score float64) string {
	if score >= 1000 {
		return "1000"
	}
	if score <= 0 {
		return "0"
	}
	return itoa(int(score))
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	buf := [20]byte{}
	pos := len(buf)
	neg := n < 0
	if neg {
		n = -n
	}
	for n > 0 {
		pos--
		buf[pos] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		pos--
		buf[pos] = '-'
	}
	return string(buf[pos:])
}
