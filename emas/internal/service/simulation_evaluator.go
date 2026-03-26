package service

import (
	"context"
	"emas/internal/domain"
	"math"
	"sort"
	"time"
)

type Scenario struct {
	Proposal    *SchedulingProposal
	StrategyID  string
	ScenarioID  string
	VariantName string
}

type ScenarioScore struct {
	ScenarioID string
	Total      float64

	TardinessMins int
	PredDelayProb float64
	PredDelayMins int
	Utilization   float64

	Pruned      bool
	PruneReason string
}

type Weights struct {
	Tardiness   float64
	DelayRisk   float64
	Utilization float64
	Deviation   float64
}

type Evaluator struct {
	Now         time.Time
	Weights     Weights
	UtilWindow  time.Duration
	MaxScenarios int
	Budget      time.Duration
}

func DefaultEvaluator(now time.Time) *Evaluator {
	return &Evaluator{
		Now:         now,
		Weights:     Weights{Tardiness: 0.40, DelayRisk: 0.40, Utilization: 0.20, Deviation: 0.25},
		UtilWindow:  24 * time.Hour,
		MaxScenarios: 9,
		Budget:      150 * time.Millisecond,
	}
}

type EvaluationResult struct {
	Winner *SchedulingProposal
	Scores []ScenarioScore
}

func (e *Evaluator) Evaluate(ctx context.Context, svc *AIPredictiveService, job *domain.Job, targetCompletion *time.Time, scenarios []Scenario) (*EvaluationResult, error) {
	start := time.Now()
	if e.Now.IsZero() {
		e.Now = time.Now()
	}
	if e.UtilWindow <= 0 {
		e.UtilWindow = 24 * time.Hour
	}
	if e.MaxScenarios <= 0 {
		e.MaxScenarios = 9
	}
	if e.Budget <= 0 {
		e.Budget = 150 * time.Millisecond
	}

	if len(scenarios) > e.MaxScenarios {
		scenarios = scenarios[:e.MaxScenarios]
	}

	// Load deviation penalty weight (DB-backed) if available.
	if svc != nil && svc.settingsRepo != nil {
		if w, err := svc.settingsRepo.GetFloat("scheduling.deviation_penalty_weight", e.Weights.Deviation); err == nil {
			e.Weights.Deviation = w
		}
	}

	// Load current plan (applied slots) once per job for deviation calculation.
	var applied []domain.JobStepScheduleSlots
	if svc != nil && svc.slotRepo != nil && job != nil {
		if slots, err := svc.slotRepo.ListByJobID(job.JobID); err == nil {
			for _, s := range slots {
				if s.Status == domain.SlotStatusPlanned || s.Status == domain.SlotStatusRunning {
					applied = append(applied, s)
				}
			}
		}
	}
	appliedIndex := indexAppliedSlotsByStep(applied)

	// ML-first risk (with fallback already handled inside buildDelayRisk).
	// Note: This risk is job-state based (uses latest snapshot); we reuse it across scenarios.
	var jobRisk *DelayRiskDetail
	if svc != nil && job != nil {
		jobRisk, _ = svc.buildDelayRisk(*job)
	}
	riskNorm := 0.0
	predDelayProb := 0.0
	predDelayMins := 0
	if jobRisk != nil {
		predDelayProb = clamp01(jobRisk.ProbabilityOfDelay)
		predDelayMins = maxInt(jobRisk.PredictedDelayMins, 0)
		if predDelayProb > 0 {
			riskNorm = predDelayProb
		} else if predDelayMins > 0 {
			riskNorm = math.Min(1.0, float64(predDelayMins)/240.0)
		}
	}

	bestScore := math.Inf(1)
	var best *SchedulingProposal
	scores := make([]ScenarioScore, 0, len(scenarios))

	for _, sc := range scenarios {
		if time.Since(start) > e.Budget {
			break
		}
		select {
		case <-ctx.Done():
			return &EvaluationResult{Winner: best, Scores: scores}, nil
		default:
		}

		p := sc.Proposal
		if p == nil || !p.Feasible || len(p.ProposedSlots) == 0 {
			scores = append(scores, ScenarioScore{
				ScenarioID:  sc.ScenarioID,
				Pruned:      true,
				PruneReason: "infeasible_or_empty",
				Total:       math.Inf(1),
			})
			continue
		}

		// Compute completion (use proposal.EstimatedCompletion if present, else max slot end).
		completion := proposalCompletion(p)
		deadline := jobDeadline(job, targetCompletion)
		tardinessMins := 0
		if completion != nil && !deadline.IsZero() && completion.After(deadline) {
			tardinessMins = int(completion.Sub(deadline).Minutes())
		}

		tardinessNorm := math.Min(1.0, float64(maxInt(tardinessMins, 0))/480.0) // cap @ 8h

		// Lower bound (skip expensive parts if it can't beat best).
		lb := e.Weights.Tardiness*tardinessNorm + e.Weights.Utilization*0.0
		if lb >= bestScore {
			scores = append(scores, ScenarioScore{
				ScenarioID:    sc.ScenarioID,
				Pruned:        true,
				PruneReason:   "bound_dominated",
				Total:         lb,
				TardinessMins: tardinessMins,
				PredDelayProb: predDelayProb,
				PredDelayMins: predDelayMins,
			})
			continue
		}

		utilNorm := utilizationProxy(p, e.Now, e.Now.Add(e.UtilWindow))

		// Deviation from current plan (anti-nervousness).
		deviationNorm := deviationFromPlanNorm(p, appliedIndex)

		total := e.Weights.Tardiness*tardinessNorm +
			e.Weights.DelayRisk*riskNorm +
			e.Weights.Utilization*utilNorm +
			e.Weights.Deviation*deviationNorm
		ss := ScenarioScore{
			ScenarioID:    sc.ScenarioID,
			Total:         total,
			TardinessMins: tardinessMins,
			PredDelayProb: predDelayProb,
			PredDelayMins: predDelayMins,
			Utilization:   utilNorm,
		}
		scores = append(scores, ss)
		if total < bestScore {
			bestScore = total
			best = p
		}
	}

	sort.SliceStable(scores, func(i, j int) bool { return scores[i].Total < scores[j].Total })
	return &EvaluationResult{Winner: best, Scores: scores}, nil
}

func clamp01(x float64) float64 {
	if x < 0 {
		return 0
	}
	if x > 1 {
		return 1
	}
	return x
}

func jobDeadline(job *domain.Job, targetCompletion *time.Time) time.Time {
	if targetCompletion != nil && !targetCompletion.IsZero() {
		return *targetCompletion
	}
	if job != nil && !job.Deadline.IsZero() {
		return job.Deadline
	}
	return time.Time{}
}

func proposalCompletion(p *SchedulingProposal) *time.Time {
	if p == nil {
		return nil
	}
	if p.EstimatedCompletion != nil {
		return p.EstimatedCompletion
	}
	var maxEnd *time.Time
	for i := range p.ProposedSlots {
		end := p.ProposedSlots[i].ScheduledEnd
		if maxEnd == nil || end.After(*maxEnd) {
			t := end
			maxEnd = &t
		}
	}
	return maxEnd
}

func utilizationProxy(p *SchedulingProposal, winStart, winEnd time.Time) float64 {
	if p == nil || !winEnd.After(winStart) {
		return 0
	}
	winMins := winEnd.Sub(winStart).Minutes()
	if winMins <= 0 {
		return 0
	}
	byMachine := map[string]float64{}
	for _, s := range p.ProposedSlots {
		ov := overlapMinutes(s.ScheduledStart, s.ScheduledEnd, winStart, winEnd)
		if ov <= 0 {
			continue
		}
		byMachine[s.MachineID] += ov
	}
	if len(byMachine) == 0 {
		return 0
	}
	sumUtil := 0.0
	for _, mins := range byMachine {
		sumUtil += clamp01(mins / winMins)
	}
	return clamp01(sumUtil / float64(len(byMachine)))
}

func overlapMinutes(aStart, aEnd, bStart, bEnd time.Time) float64 {
	if !aEnd.After(aStart) || !bEnd.After(bStart) {
		return 0
	}
	start := aStart
	if bStart.After(start) {
		start = bStart
	}
	end := aEnd
	if bEnd.Before(end) {
		end = bEnd
	}
	if !end.After(start) {
		return 0
	}
	return end.Sub(start).Minutes()
}

func indexAppliedSlotsByStep(slots []domain.JobStepScheduleSlots) map[string]domain.JobStepScheduleSlots {
	m := make(map[string]domain.JobStepScheduleSlots, len(slots))
	for _, s := range slots {
		if s.JobStepID == "" {
			continue
		}
		// We only keep one slot per step for deviation comparison; for split/parallel steps,
		// this is an approximation but still acts as a stabilizing penalty.
		if existing, ok := m[s.JobStepID]; ok {
			if s.ScheduledStart.Before(existing.ScheduledStart) {
				m[s.JobStepID] = s
			}
			continue
		}
		m[s.JobStepID] = s
	}
	return m
}

func deviationFromPlanNorm(p *SchedulingProposal, appliedByStep map[string]domain.JobStepScheduleSlots) float64 {
	if p == nil || len(appliedByStep) == 0 {
		return 0
	}
	totalDeltaMins := 0
	for _, ps := range p.ProposedSlots {
		if ps.JobStepID == "" {
			continue
		}
		applied, ok := appliedByStep[ps.JobStepID]
		if !ok {
			continue
		}
		// Machine change counts as a strong deviation; approximate as 60 minutes.
		if applied.MachineID != "" && ps.MachineID != "" && applied.MachineID != ps.MachineID {
			totalDeltaMins += 60
		}
		// Time shift deviation (rounded to minute).
		a := applied.ScheduledStart.UTC().Truncate(time.Minute)
		b := ps.ScheduledStart.UTC().Truncate(time.Minute)
		d := int(a.Sub(b).Minutes())
		if d < 0 {
			d = -d
		}
		totalDeltaMins += d
	}
	// Normalize: cap at 4h (240 mins).
	if totalDeltaMins <= 0 {
		return 0
	}
	if totalDeltaMins >= 240 {
		return 1
	}
	return float64(totalDeltaMins) / 240.0
}

