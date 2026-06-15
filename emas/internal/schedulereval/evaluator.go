package schedulereval

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"emas/internal/service"
)

type EvaluateOptions struct {
	BaselineHash string
}

type slotRef struct {
	ProposalID string
	JobID      string
	ProductID  string
	Slot       service.ProposedSlot
}

func Evaluate(result EndpointResult, opts EvaluateOptions) Scorecard {
	score := Scorecard{
		SchemaVersion: 1,
		Metadata:      result.Metadata,
		Stability: StabilityMetrics{
			BaselineHash: opts.BaselineHash,
		},
	}
	if score.Metadata.Timestamp.IsZero() {
		score.Metadata.Timestamp = time.Now().UTC()
	}

	proposals := nonNilProposals(result.Proposals)
	score.Performance.ProposalCount = len(proposals)
	score.Performance.RuntimeMS = result.Runtime.Milliseconds()
	if result.Runtime > 0 && len(proposals) > 0 {
		score.Performance.JobsPerSecond = float64(len(proposals)) / result.Runtime.Seconds()
	}
	if result.Summary != nil {
		score.Performance.BlockedCount = result.Summary.Blocked
		score.Quality.OnTimeCount = result.Summary.OnTimeCount
		score.Quality.LateCount = result.Summary.LateCount
		score.Material.AggregateReplenishmentCount = len(result.Summary.MaterialReplenishmentAggregate)
		score.Material.AggregateMaterialIDs = aggregateMaterialIDs(result.Summary.MaterialReplenishmentAggregate)
		score.Material.AggregateAccelerationCount = len(result.Summary.MaterialAccelerationAggregate)
		score.Material.AggregateAccelerationIDs = aggregateMaterialIDs(result.Summary.MaterialAccelerationAggregate)
		if result.Summary.Skipped > 0 {
			score.Feasibility.SilentExcludedJobs = result.Summary.Skipped
			score.addFailure(Finding{
				Code:     "silent_excluded_jobs",
				Severity: SeverityError,
				Message:  fmt.Sprintf("summary reports %d skipped job(s); evaluator treats skipped scheduler inputs as a hard correctness failure", result.Summary.Skipped),
			})
		}
	}
	if result.Partial {
		score.addWarning(Finding{
			Code:     "partial_scheduler_result",
			Severity: SeverityWarning,
			Message:  "scheduler returned a partial result; quality and stability metrics may not be comparable",
		})
	}

	slots := make([]slotRef, 0)
	seenProposalJobs := make(map[string]struct{}, len(proposals))
	for _, p := range proposals {
		seenProposalJobs[p.JobID] = struct{}{}
		if p.Feasible {
			score.Feasibility.FeasibleJobs++
			if len(p.ProposedSlots) == 0 {
				score.Correctness.MissingSlotsCount++
				score.Feasibility.FeasibleWithoutSlots++
				score.addFailure(Finding{
					Code:       "feasible_without_slots",
					Severity:   SeverityError,
					Message:    "feasible proposal has no proposed slots",
					JobID:      p.JobID,
					ProposalID: p.ProposalID,
				})
			}
		} else {
			score.Feasibility.InfeasibleJobs++
			score.Feasibility.BlockedJobIDs = append(score.Feasibility.BlockedJobIDs, p.JobID)
			if len(p.BlockedReasons) == 0 && !hasShortageEvidence(p) {
				score.Feasibility.InfeasibleWithoutReason++
				score.addFailure(Finding{
					Code:       "infeasible_without_reason",
					Severity:   SeverityError,
					Message:    "infeasible proposal has no reason code or actionable shortage evidence",
					JobID:      p.JobID,
					ProposalID: p.ProposalID,
				})
			}
			if blockedReasonsContainMaterialShortage(p.BlockedReasons) && !hasShortageEvidence(p) {
				score.Feasibility.InfeasibleWithoutShortageEvidence++
				score.addFailure(Finding{
					Code:       "material_shortage_without_evidence",
					Severity:   SeverityError,
					Message:    "proposal is blocked by material shortage but exposes no shortage rows or resolution evidence",
					JobID:      p.JobID,
					ProposalID: p.ProposalID,
				})
			}
		}
		if proposalHasMaterialShortage(p) {
			score.Material.MaterialShortageProposalCount++
			score.Material.MaterialShortageCount += len(p.MaterialShortages)
		}
		score.Material.ChildMaterialEvidenceCount += childMaterialEvidenceCount(p)
		tardiness := proposalTardiness(p)
		score.Quality.TotalTardinessMins += tardiness
		score.Quality.WeightedTardinessMins += tardiness
		score.Quality.MaxTardinessMins = maxInt(score.Quality.MaxTardinessMins, tardiness)
		if tardiness > 0 {
			score.Quality.TopLateJobs = append(score.Quality.TopLateJobs, lateJobMetric(p, tardiness))
		}
		for _, s := range p.ProposedSlots {
			ref := slotRef{ProposalID: p.ProposalID, JobID: p.JobID, ProductID: p.ProductID, Slot: s}
			slots = append(slots, ref)
			validateSlotRange(&score, ref)
		}
		validateProposalStepOrder(&score, p)
		validateInventoryActionTimes(&score, p)
	}
	sort.Strings(score.Feasibility.BlockedJobIDs)

	validateDuplicateSlots(&score, slots)
	validateMachineOverlaps(&score, slots)
	applyQualityMetrics(&score, slots)
	limitTopLateJobs(&score, 10)
	score.Stability.ScheduleHash = StableScheduleHash(proposals)
	score.RecalculateScore()
	return score
}

func nonNilProposals(input []*service.SchedulingProposal) []*service.SchedulingProposal {
	out := make([]*service.SchedulingProposal, 0, len(input))
	for _, p := range input {
		if p != nil {
			out = append(out, p)
		}
	}
	return out
}

func aggregateMaterialIDs(lines []service.BatchMaterialReplenishmentLine) []string {
	seen := map[string]struct{}{}
	for _, line := range lines {
		if line.MaterialID != "" {
			seen[line.MaterialID] = struct{}{}
		}
	}
	ids := make([]string, 0, len(seen))
	for id := range seen {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func validateSlotRange(score *Scorecard, ref slotRef) {
	s := ref.Slot
	if s.ScheduledStart.IsZero() || s.ScheduledEnd.IsZero() || !s.ScheduledEnd.After(s.ScheduledStart) {
		score.Correctness.InvalidTimeRangeCount++
		score.addFailure(Finding{
			Code:       "invalid_time_range",
			Severity:   SeverityError,
			Message:    "slot has empty or non-positive scheduled time range",
			JobID:      ref.JobID,
			ProposalID: ref.ProposalID,
			MachineID:  s.MachineID,
			StepID:     s.StepID,
		})
	}
}

func validateDuplicateSlots(score *Scorecard, slots []slotRef) {
	seen := map[string]slotRef{}
	for _, ref := range slots {
		s := ref.Slot
		key := strings.Join([]string{
			ref.JobID,
			s.JobStepID,
			s.MachineID,
			s.ScheduledStart.UTC().Format(time.RFC3339Nano),
			s.ScheduledEnd.UTC().Format(time.RFC3339Nano),
		}, "|")
		if prior, ok := seen[key]; ok {
			score.Correctness.DuplicateSlotCount++
			score.addFailure(Finding{
				Code:       "duplicate_slot",
				Severity:   SeverityError,
				Message:    fmt.Sprintf("slot duplicates proposal %s for the same job step, machine and time range", prior.ProposalID),
				JobID:      ref.JobID,
				ProposalID: ref.ProposalID,
				MachineID:  s.MachineID,
				StepID:     s.StepID,
			})
			continue
		}
		seen[key] = ref
	}
}

func validateMachineOverlaps(score *Scorecard, slots []slotRef) {
	byMachine := map[string][]slotRef{}
	for _, ref := range slots {
		if ref.Slot.MachineID == "" || ref.Slot.ScheduledStart.IsZero() || ref.Slot.ScheduledEnd.IsZero() {
			continue
		}
		byMachine[ref.Slot.MachineID] = append(byMachine[ref.Slot.MachineID], ref)
	}
	for machineID, refs := range byMachine {
		sort.SliceStable(refs, func(i, j int) bool {
			if refs[i].Slot.ScheduledStart.Equal(refs[j].Slot.ScheduledStart) {
				return refs[i].Slot.ScheduledEnd.Before(refs[j].Slot.ScheduledEnd)
			}
			return refs[i].Slot.ScheduledStart.Before(refs[j].Slot.ScheduledStart)
		})
		for i := 1; i < len(refs); i++ {
			prev := refs[i-1]
			curr := refs[i]
			if curr.Slot.ScheduledStart.Before(prev.Slot.ScheduledEnd) {
				score.Correctness.MachineOverlapCount++
				score.addFailure(Finding{
					Code:       "machine_overlap",
					Severity:   SeverityError,
					Message:    fmt.Sprintf("slot overlaps previous slot for job %s ending at %s", prev.JobID, prev.Slot.ScheduledEnd.UTC().Format(time.RFC3339)),
					JobID:      curr.JobID,
					ProposalID: curr.ProposalID,
					MachineID:  machineID,
					StepID:     curr.Slot.StepID,
				})
			}
		}
	}
}

func validateProposalStepOrder(score *Scorecard, p *service.SchedulingProposal) {
	if len(p.ProposedSlots) < 2 {
		return
	}
	slots := append([]service.ProposedSlot(nil), p.ProposedSlots...)
	sort.SliceStable(slots, func(i, j int) bool {
		if slots[i].BatchSequence == slots[j].BatchSequence {
			return slots[i].ScheduledStart.Before(slots[j].ScheduledStart)
		}
		return slots[i].BatchSequence < slots[j].BatchSequence
	})
	for i := 1; i < len(slots); i++ {
		prev := slots[i-1]
		curr := slots[i]
		if curr.BatchSequence > prev.BatchSequence && curr.ScheduledStart.Before(prev.ScheduledEnd) {
			score.Correctness.StepOrderViolationCount++
			score.addFailure(Finding{
				Code:       "step_order_violation",
				Severity:   SeverityError,
				Message:    fmt.Sprintf("step batch_sequence %d starts before previous batch_sequence %d ends", curr.BatchSequence, prev.BatchSequence),
				JobID:      p.JobID,
				ProposalID: p.ProposalID,
				MachineID:  curr.MachineID,
				StepID:     curr.StepID,
			})
		}
	}
}

func validateInventoryActionTimes(score *Scorecard, p *service.SchedulingProposal) {
	if len(p.InventoryActions) == 0 || len(p.ProposedSlots) == 0 {
		return
	}
	slotStartByStep := map[string]time.Time{}
	for _, slot := range p.ProposedSlots {
		if slot.JobStepID != "" && !slot.ScheduledStart.IsZero() {
			if existing, ok := slotStartByStep[slot.JobStepID]; !ok || slot.ScheduledStart.Before(existing) {
				slotStartByStep[slot.JobStepID] = slot.ScheduledStart
			}
		}
	}
	for _, action := range p.InventoryActions {
		if action.ActionType != "reserve_material" || action.JobStepID == "" || action.EffectiveAt.IsZero() {
			continue
		}
		slotStart, ok := slotStartByStep[action.JobStepID]
		if !ok {
			continue
		}
		if action.EffectiveAt.After(slotStart) {
			score.Material.FutureArrivalViolationCount++
			score.addFailure(Finding{
				Code:       "material_reserve_after_slot_start",
				Severity:   SeverityError,
				Message:    "material reservation effective time is after the consuming slot starts",
				JobID:      p.JobID,
				ProposalID: p.ProposalID,
				StepID:     action.JobStepID,
				MaterialID: action.ResourceID,
			})
		}
	}
}

func applyQualityMetrics(score *Scorecard, slots []slotRef) {
	if len(slots) == 0 {
		return
	}
	var minStart, maxEnd time.Time
	busyByMachine := map[string]time.Duration{}
	byMachine := map[string][]slotRef{}
	for _, ref := range slots {
		s := ref.Slot
		if s.ScheduledStart.IsZero() || s.ScheduledEnd.IsZero() || !s.ScheduledEnd.After(s.ScheduledStart) {
			continue
		}
		if minStart.IsZero() || s.ScheduledStart.Before(minStart) {
			minStart = s.ScheduledStart
		}
		if maxEnd.IsZero() || s.ScheduledEnd.After(maxEnd) {
			maxEnd = s.ScheduledEnd
		}
		busyByMachine[s.MachineID] += s.ScheduledEnd.Sub(s.ScheduledStart)
		byMachine[s.MachineID] = append(byMachine[s.MachineID], ref)
	}
	if minStart.IsZero() || maxEnd.IsZero() || !maxEnd.After(minStart) {
		return
	}
	makespan := maxEnd.Sub(minStart)
	score.Quality.MakespanMins = int(math.Round(makespan.Minutes()))
	var busy time.Duration
	for _, d := range busyByMachine {
		busy += d
	}
	if machineCount := len(busyByMachine); machineCount > 0 {
		score.Quality.MachineUtilizationPct = round2(100 * busy.Seconds() / (makespan.Seconds() * float64(machineCount)))
	}
	for _, refs := range byMachine {
		sort.SliceStable(refs, func(i, j int) bool {
			return refs[i].Slot.ScheduledStart.Before(refs[j].Slot.ScheduledStart)
		})
		for i := 1; i < len(refs); i++ {
			gap := refs[i].Slot.ScheduledStart.Sub(refs[i-1].Slot.ScheduledEnd)
			if gap > 0 {
				score.Quality.WaitTimeMins += int(math.Round(gap.Minutes()))
			}
			if refs[i].ProductID != "" && refs[i-1].ProductID != "" && refs[i].ProductID != refs[i-1].ProductID {
				score.Quality.SetupSwitches++
			}
		}
	}
}

func proposalTardiness(p *service.SchedulingProposal) int {
	if p == nil || p.DeadlineStatus == nil {
		return 0
	}
	if p.DeadlineStatus.TardinessMins < 0 {
		return 0
	}
	return p.DeadlineStatus.TardinessMins
}

func lateJobMetric(p *service.SchedulingProposal, tardiness int) LateJobMetric {
	metric := LateJobMetric{
		JobID:         p.JobID,
		ProductID:     p.ProductID,
		TardinessMins: tardiness,
	}
	if p.DeadlineStatus != nil && !p.DeadlineStatus.Deadline.IsZero() {
		deadline := p.DeadlineStatus.Deadline
		metric.Deadline = &deadline
	}
	if p.EstimatedCompletion != nil && !p.EstimatedCompletion.IsZero() {
		completion := *p.EstimatedCompletion
		metric.EstimatedCompletion = &completion
	}
	return metric
}

func limitTopLateJobs(score *Scorecard, limit int) {
	if len(score.Quality.TopLateJobs) == 0 {
		return
	}
	sort.SliceStable(score.Quality.TopLateJobs, func(i, j int) bool {
		left := score.Quality.TopLateJobs[i]
		right := score.Quality.TopLateJobs[j]
		if left.TardinessMins != right.TardinessMins {
			return left.TardinessMins > right.TardinessMins
		}
		return left.JobID < right.JobID
	})
	if limit > 0 && len(score.Quality.TopLateJobs) > limit {
		score.Quality.TopLateJobs = score.Quality.TopLateJobs[:limit]
	}
}

func hasShortageEvidence(p *service.SchedulingProposal) bool {
	if p == nil {
		return false
	}
	if len(p.MaterialShortages) > 0 || len(p.ShortageResolutions) > 0 {
		return true
	}
	for _, dep := range p.DependentJobs {
		if dep.ReplenishmentSuggestion != nil || len(dep.ResolutionOptions) > 0 || dep.ShortageQty > 0 {
			return true
		}
	}
	return false
}

func proposalHasMaterialShortage(p *service.SchedulingProposal) bool {
	if p == nil {
		return false
	}
	if blockedReasonsContainMaterialShortage(p.BlockedReasons) {
		return true
	}
	if !p.Feasible && hasShortageEvidence(p) {
		return true
	}
	return false
}

func childMaterialEvidenceCount(p *service.SchedulingProposal) int {
	count := 0
	for _, dep := range p.DependentJobs {
		if dep.ReplenishmentSuggestion != nil {
			count++
		}
		for _, opt := range dep.ResolutionOptions {
			if opt.DependencyProductID != "" || opt.Replenishment != nil {
				count++
			}
		}
	}
	return count
}

func blockedReasonsContainMaterialShortage(reasons []string) bool {
	for _, reason := range reasons {
		r := strings.ToLower(reason)
		if strings.Contains(r, "material_shortage") || strings.Contains(r, "material shortage") {
			return true
		}
	}
	return false
}

func StableScheduleHash(proposals []*service.SchedulingProposal) string {
	lines := make([]string, 0)
	for _, p := range nonNilProposals(proposals) {
		status := "infeasible"
		if p.Feasible {
			status = "feasible"
		}
		reasons := append([]string(nil), p.BlockedReasons...)
		sort.Strings(reasons)
		if len(p.ProposedSlots) == 0 {
			lines = append(lines, strings.Join([]string{p.JobID, p.ProductID, status, strings.Join(reasons, ",")}, "|"))
			continue
		}
		slots := append([]service.ProposedSlot(nil), p.ProposedSlots...)
		sort.SliceStable(slots, func(i, j int) bool {
			if slots[i].ScheduledStart.Equal(slots[j].ScheduledStart) {
				if slots[i].MachineID == slots[j].MachineID {
					return slots[i].JobStepID < slots[j].JobStepID
				}
				return slots[i].MachineID < slots[j].MachineID
			}
			return slots[i].ScheduledStart.Before(slots[j].ScheduledStart)
		})
		for _, s := range slots {
			lines = append(lines, strings.Join([]string{
				p.JobID,
				p.ProductID,
				status,
				strings.Join(reasons, ","),
				s.JobStepID,
				s.StepID,
				s.MachineID,
				s.ScheduledStart.UTC().Format(time.RFC3339Nano),
				s.ScheduledEnd.UTC().Format(time.RFC3339Nano),
				fmt.Sprintf("%d", s.QuantityPlanned),
			}, "|"))
		}
	}
	sort.Strings(lines)
	sum := sha256.Sum256([]byte(strings.Join(lines, "\n")))
	return hex.EncodeToString(sum[:])
}

func (s *Scorecard) addFailure(f Finding) {
	if f.Severity == "" {
		f.Severity = SeverityError
	}
	s.Failures = append(s.Failures, f)
}

func (s *Scorecard) addWarning(f Finding) {
	if f.Severity == "" {
		f.Severity = SeverityWarning
	}
	s.Warnings = append(s.Warnings, f)
}

func (s *Scorecard) RecalculateScore() {
	correctnessPenalty :=
		25*len(s.Failures) +
			8*s.Correctness.MachineOverlapCount +
			8*s.Correctness.InvalidTimeRangeCount +
			6*s.Correctness.MissingSlotsCount +
			6*s.Correctness.DuplicateSlotCount +
			6*s.Correctness.StepOrderViolationCount +
			6*s.Correctness.IncompatibleResourceUseCount +
			5*s.Feasibility.FeasibleWithoutSlots +
			5*s.Feasibility.InfeasibleWithoutReason +
			5*s.Feasibility.InfeasibleWithoutShortageEvidence +
			5*s.Feasibility.SilentExcludedJobs +
			5*s.Material.UnaccountedNegativeLedgerCount +
			5*s.Material.FutureArrivalViolationCount

	totalTardinessHours := math.Max(0, float64(s.Quality.TotalTardinessMins)/60.0)
	maxTardinessHours := math.Max(0, float64(s.Quality.MaxTardinessMins)/60.0)
	waitHours := math.Max(0, float64(s.Quality.WaitTimeMins)/60.0)
	qualityPenalty :=
		minInt(45, 3*s.Quality.LateCount) +
			minInt(55, int(math.Ceil(math.Sqrt(totalTardinessHours)*0.45))) +
			minInt(20, int(math.Ceil(math.Sqrt(maxTardinessHours)*0.35))) +
			minInt(10, int(math.Ceil(math.Sqrt(waitHours)*0.20))) +
			minInt(8, int(math.Ceil(float64(s.Quality.SetupSwitches)/5.0)))

	performancePenalty := 0
	if s.Performance.RuntimeMS > 0 {
		performancePenalty = int(math.Ceil(float64(s.Performance.RuntimeMS) / 30000.0))
	}
	if s.Performance.JobsPerSecond > 0 && s.Performance.JobsPerSecond < 0.2 {
		performancePenalty += 5
	}

	correctness := clampScore(100 - float64(correctnessPenalty))
	quality := clampScore(100 - float64(qualityPenalty))
	performance := clampScore(100 - float64(performancePenalty))
	overall := round2(correctness*0.55 + quality*0.35 + performance*0.10)
	if len(s.Failures) > 0 && overall > correctness {
		overall = correctness
	}
	s.Score = ScoreBreakdown{
		HardGatePassed:   len(s.Failures) == 0,
		CorrectnessScore: correctness,
		QualityScore:     quality,
		PerformanceScore: performance,
		OverallScore:     overall,
	}
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func round2(v float64) float64 {
	return math.Round(v*100) / 100
}

func clampScore(v float64) float64 {
	if v < 0 {
		return 0
	}
	if v > 100 {
		return 100
	}
	return round2(v)
}
