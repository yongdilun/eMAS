package service

import (
	"context"
	"emas/internal/domain"
	"emas/pkg/logger"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"go.uber.org/zap"
)

// HeuristicStrategy is a fast, bounded scheduling policy for generating a proposal.
type HeuristicStrategy interface {
	ID() string
	Describe() string
	Applicable(job *domain.Job, preview *SolverPreview, tentativeSlots []TentativeSlot, targetCompletion *time.Time) bool
	Generate(ctx context.Context, svc *AIPredictiveService, job *domain.Job, preview *SolverPreview, tentativeSlots []TentativeSlot, targetCompletion *time.Time) (*SchedulingProposal, error)
}

type heuristicContext struct {
	now       time.Time
	cache     map[candidateCacheKey][]CandidateMachine
	loadScore map[string]float64
}

type candidateCacheKey struct {
	jobStepID string
	startMin  int64
	endMin    int64
	hash      uint64
}

func newHeuristicContext(now time.Time) *heuristicContext {
	return &heuristicContext{
		now:       now,
		cache:     map[candidateCacheKey][]CandidateMachine{},
		loadScore: map[string]float64{},
	}
}

func (h *heuristicContext) key(jobStepID string, start, end time.Time, tentative []TentativeSlot) candidateCacheKey {
	return candidateCacheKey{
		jobStepID: jobStepID,
		startMin:  start.UTC().Truncate(time.Minute).Unix(),
		endMin:    end.UTC().Truncate(time.Minute).Unix(),
		hash:      tentativeHash(tentative),
	}
}

func tentativeHash(slots []TentativeSlot) uint64 {
	// Very cheap hash: stable-enough for per-request caching.
	var h uint64 = 1469598103934665603
	const prime uint64 = 1099511628211
	for _, s := range slots {
		for i := 0; i < len(s.MachineID); i++ {
			h ^= uint64(s.MachineID[i])
			h *= prime
		}
		h ^= uint64(s.ScheduledStart.UTC().Truncate(time.Minute).Unix())
		h *= prime
		h ^= uint64(s.ScheduledEnd.UTC().Truncate(time.Minute).Unix())
		h *= prime
	}
	return h
}

func (h *heuristicContext) candidatesWithCache(svc *AIPredictiveService, jobStepID string, start, end time.Time, tentative []TentativeSlot) ([]CandidateMachine, error) {
	k := h.key(jobStepID, start, end, tentative)
	if cached, ok := h.cache[k]; ok {
		return cached, nil
	}
	cs, err := svc.scheduling.CandidateMachinesForStepWithTentative(jobStepID, start, end, tentative)
	if err != nil {
		return nil, err
	}
	h.cache[k] = cs
	return cs, nil
}

func (h *heuristicContext) computeLoadScoresOnce(svc *AIPredictiveService) {
	if len(h.loadScore) > 0 {
		return
	}
	machines, err := svc.machineRepo.ListAll()
	if err != nil {
		return
	}
	for _, m := range machines {
		// Lower is better; base on utilization_rate if available.
		h.loadScore[m.MachineID] = m.UtilizationRate
	}
}

func buildBaseProposal(job *domain.Job, engineVersion string, now time.Time) *SchedulingProposal {
	return &SchedulingProposal{
		JobID:          job.JobID,
		ProductID:      job.ProductID,
		Engine:         "heuristic",
		EngineVersion:  engineVersion,
		GeneratedAt:    now.UTC(),
		Feasible:       true,
		EarliestStart:  now,
		ProposedSlots:  make([]ProposedSlot, 0),
		Summary:        make([]string, 0, 4),
		BlockedReasons: make([]string, 0, 4),
	}
}

func combinedTentative(base []TentativeSlot, slots []ProposedSlot) []TentativeSlot {
	out := make([]TentativeSlot, 0, len(base)+len(slots))
	out = append(out, base...)
	for _, ps := range slots {
		out = append(out, TentativeSlot{MachineID: ps.MachineID, ScheduledStart: ps.ScheduledStart, ScheduledEnd: ps.ScheduledEnd})
	}
	return out
}

func proposalsDistinct(a, b *SchedulingProposal) bool {
	if a == nil || b == nil {
		return true
	}
	if len(a.ProposedSlots) != len(b.ProposedSlots) {
		return true
	}
	for i := range a.ProposedSlots {
		as := a.ProposedSlots[i]
		bs := b.ProposedSlots[i]
		if as.MachineID != bs.MachineID {
			return true
		}
		// Different timing by >= 1 minute counts as distinct.
		if !as.ScheduledStart.UTC().Truncate(time.Minute).Equal(bs.ScheduledStart.UTC().Truncate(time.Minute)) ||
			!as.ScheduledEnd.UTC().Truncate(time.Minute).Equal(bs.ScheduledEnd.UTC().Truncate(time.Minute)) {
			return true
		}
	}
	return false
}

func defaultHeuristicPortfolio() []HeuristicStrategy {
	return []HeuristicStrategy{
		GreedyEarliestFinish{},
		GreedySecondBestFinish{},
		GreedyEarliestStart{},
		LeastLoadedMachine{},
		DeadlineBiasedLastStep{},
	}
}

func scoreStrategy(s HeuristicStrategy, job *domain.Job, preview *SolverPreview, targetCompletion *time.Time) float64 {
	score := 0.0
	if targetCompletion != nil {
		score += 10
	}
	if preview != nil && preview.CanStartNow {
		score += 5
	}
	// Slightly prefer simple jobs when budgeted.
	if preview != nil {
		score += 1.0 / float64(maxInt(len(preview.Steps), 1))
	}
	_ = job
	_ = s
	return score
}

func selectTopStrategies(strategies []HeuristicStrategy, k int, job *domain.Job, preview *SolverPreview, tentativeSlots []TentativeSlot, targetCompletion *time.Time) []HeuristicStrategy {
	type scored struct {
		s     HeuristicStrategy
		score float64
	}
	cands := make([]scored, 0, len(strategies))
	for _, st := range strategies {
		if !st.Applicable(job, preview, tentativeSlots, targetCompletion) {
			continue
		}
		cands = append(cands, scored{s: st, score: scoreStrategy(st, job, preview, targetCompletion)})
	}
	sort.SliceStable(cands, func(i, j int) bool {
		if cands[i].score == cands[j].score {
			return cands[i].s.ID() < cands[j].s.ID()
		}
		return cands[i].score > cands[j].score
	})
	if k <= 0 || k > len(cands) {
		k = len(cands)
	}
	out := make([]HeuristicStrategy, 0, k)
	for i := 0; i < k; i++ {
		out = append(out, cands[i].s)
	}
	return out
}

// ─── Strategy: Greedy earliest finish (baseline) ──────────────────────────────

type GreedyEarliestFinish struct{}

func (s GreedyEarliestFinish) ID() string { return "greedy_earliest_finish" }
func (s GreedyEarliestFinish) Describe() string {
	return "Pick machine that yields earliest finish (baseline)."
}
func (s GreedyEarliestFinish) Applicable(_ *domain.Job, _ *SolverPreview, _ []TentativeSlot, _ *time.Time) bool {
	return true
}
func (s GreedyEarliestFinish) Generate(ctx context.Context, svc *AIPredictiveService, job *domain.Job, preview *SolverPreview, tentativeSlots []TentativeSlot, targetCompletion *time.Time) (*SchedulingProposal, error) {
	h := newHeuristicContext(time.Now())
	return generateWithCandidateSort(ctx, svc, job, preview, tentativeSlots, targetCompletion, h, s.ID(), sortByEarliestFinish(targetCompletion))
}

// ─── Strategy: Greedy second-best by finish ───────────────────────────────────

type GreedySecondBestFinish struct{}

func (s GreedySecondBestFinish) ID() string { return "greedy_second_best_finish" }
func (s GreedySecondBestFinish) Describe() string {
	return "Pick the 2nd-ranked machine by earliest finish to force diversity."
}
func (s GreedySecondBestFinish) Applicable(_ *domain.Job, _ *SolverPreview, _ []TentativeSlot, _ *time.Time) bool {
	return true
}
func (s GreedySecondBestFinish) Generate(ctx context.Context, svc *AIPredictiveService, job *domain.Job, preview *SolverPreview, tentativeSlots []TentativeSlot, targetCompletion *time.Time) (*SchedulingProposal, error) {
	h := newHeuristicContext(time.Now())
	return generateWithCandidateSortPick(ctx, svc, job, preview, tentativeSlots, targetCompletion, h, s.ID(), sortByEarliestFinish(targetCompletion), 1, 0, 0)
}

// ─── Strategy: Greedy earliest start ──────────────────────────────────────────

type GreedyEarliestStart struct{}

func (s GreedyEarliestStart) ID() string { return "greedy_earliest_start" }
func (s GreedyEarliestStart) Describe() string {
	return "Pick machine that can start earliest (ASAP)."
}
func (s GreedyEarliestStart) Applicable(_ *domain.Job, _ *SolverPreview, _ []TentativeSlot, _ *time.Time) bool {
	return true
}
func (s GreedyEarliestStart) Generate(ctx context.Context, svc *AIPredictiveService, job *domain.Job, preview *SolverPreview, tentativeSlots []TentativeSlot, targetCompletion *time.Time) (*SchedulingProposal, error) {
	h := newHeuristicContext(time.Now())
	return generateWithCandidateSortPick(ctx, svc, job, preview, tentativeSlots, targetCompletion, h, s.ID(), sortByEarliestStart(), 0, 0, 5*time.Minute)
}

// ─── Strategy: Least loaded machine ───────────────────────────────────────────

type LeastLoadedMachine struct{}

func (s LeastLoadedMachine) ID() string { return "least_loaded_machine" }
func (s LeastLoadedMachine) Describe() string {
	return "Prefer machines with lower utilization/load proxy."
}
func (s LeastLoadedMachine) Applicable(_ *domain.Job, _ *SolverPreview, _ []TentativeSlot, _ *time.Time) bool {
	return true
}
func (s LeastLoadedMachine) Generate(ctx context.Context, svc *AIPredictiveService, job *domain.Job, preview *SolverPreview, tentativeSlots []TentativeSlot, targetCompletion *time.Time) (*SchedulingProposal, error) {
	h := newHeuristicContext(time.Now())
	h.computeLoadScoresOnce(svc)
	return generateWithCandidateSortPick(ctx, svc, job, preview, tentativeSlots, targetCompletion, h, s.ID(), sortByLeastLoaded(h.loadScore), 0, 0, 10*time.Minute)
}

// ─── Strategy: Deadline biased last step ──────────────────────────────────────

type DeadlineBiasedLastStep struct{}

func (s DeadlineBiasedLastStep) ID() string { return "deadline_biased_last_step" }
func (s DeadlineBiasedLastStep) Describe() string {
	return "Strongly prefer meeting target completion on last step."
}
func (s DeadlineBiasedLastStep) Applicable(_ *domain.Job, _ *SolverPreview, _ []TentativeSlot, targetCompletion *time.Time) bool {
	return targetCompletion != nil
}
func (s DeadlineBiasedLastStep) Generate(ctx context.Context, svc *AIPredictiveService, job *domain.Job, preview *SolverPreview, tentativeSlots []TentativeSlot, targetCompletion *time.Time) (*SchedulingProposal, error) {
	h := newHeuristicContext(time.Now())
	return generateWithCandidateSortPick(ctx, svc, job, preview, tentativeSlots, targetCompletion, h, s.ID(), sortByDeadlineBiased(targetCompletion), 0, 0, 15*time.Minute)
}

// ─── Shared generator ─────────────────────────────────────────────────────────

type candidateSorter func(step SolverPreviewStep, duration time.Duration, candidates []CandidateMachine)

type horizonPolicy struct {
	rollingWindow time.Duration
	growBy        time.Duration
	maxExpansions int
	absoluteCap   time.Duration
}

const (
	// Staged strict placement profile (user-tunable):
	// strict -> slight relax -> normal fallback -> aggressive -> last resort -> 400d hard ceiling.
	primaryHorizonDays              = 3
	slightRelaxHorizonDays          = 7
	normalFallbackHorizonDays       = 14
	aggressiveHorizonDays           = 21
	lastResortHorizonDays           = 30
	maxHorizonDays                  = 400
	primaryMaxLatenessDays          = 0
	slightRelaxMaxLatenessDays      = 2
	normalFallbackMaxLatenessDays   = 7
	aggressiveMaxLatenessDays       = 14
	lastResortMaxLatenessDays       = 30
	maxMaxLatenessDays              = 400
	hybridDeadlineBufferDays        = 1
	defaultGrowByHours              = 8
	defaultMaxExpansions            = 6
	topKMachines                    = 5
	minDistinctAttemptsForEarlyExit = 3
	maxSlicesPerStep                = 8
	minSliceMinutes                 = 15
	maxIntervalsScannedPerMachine   = 128
)

var maxGapBetweenSlices = time.Duration(-1) // negative means unlimited

type machineAttemptResult string

const (
	machineAttemptNoWindow   machineAttemptResult = "NO_WINDOW"
	machineAttemptOverlap    machineAttemptResult = "OVERLAP"
	machineAttemptPrecedence machineAttemptResult = "PRECEDENCE"
	machineAttemptCalendar   machineAttemptResult = "CALENDAR"
	machineAttemptUnknown    machineAttemptResult = "UNKNOWN"
)

type strictPlacementAttempt struct {
	MachineID string               `json:"machine"`
	Result    machineAttemptResult `json:"result_enum"`
	Signature string               `json:"signature"`
}

type splitPlanResult struct {
	Slices                  []BusyInterval
	CoveredMinutes          int
	RequiredMinutes         int
	MaxContinuousWindowMins int
	Valid                   bool
	Reason                  string
}

type strictPlacementInput struct {
	JobStepID              string
	Start                  time.Time
	Duration               time.Duration
	Quantity               int
	ProcessStep            *domain.ProcessSteps
	Tentative              []TentativeSlot
	HorizonEnd             time.Time
	MaxExpansions          int
	GrowBy                 time.Duration
	AllowNoWindowEarlyExit bool
}

type strictPlacementOutcome struct {
	Start                   time.Time
	Ok                      bool
	Reasons                 []string
	Diag                    map[string]interface{}
	Attempts                []strictPlacementAttempt
	AttemptedMachineIDs     []string
	AttemptedCount          int
	SelectedMachineID       string
	Expansions              int
	EarlyExit               bool
	EarlyExitSignature      string
	SplitSlices             []BusyInterval
	SplitUsed               bool
	CoveredMinutes          int
	RequiredMinutes         int
	MaxContinuousWindowMins int
	SplitMachineIDs         []string
}

type splitCandidateSlice struct {
	MachineID string
	Interval  BusyInterval
}

func defaultHorizonPolicy() horizonPolicy {
	// Default adaptive candidate horizon is bounded by the hard 60-day ceiling.
	return horizonPolicy{
		rollingWindow: time.Duration(primaryHorizonDays) * 24 * time.Hour,
		growBy:        time.Duration(defaultGrowByHours) * time.Hour,
		maxExpansions: defaultMaxExpansions,
		absoluteCap:   time.Duration(maxHorizonDays) * 24 * time.Hour,
	}
}

type placementStage struct {
	HorizonDays  int
	LatenessDays int
}

func placementStages() []placementStage {
	return []placementStage{
		{HorizonDays: primaryHorizonDays, LatenessDays: primaryMaxLatenessDays},
		{HorizonDays: slightRelaxHorizonDays, LatenessDays: slightRelaxMaxLatenessDays},
		{HorizonDays: normalFallbackHorizonDays, LatenessDays: normalFallbackMaxLatenessDays},
		{HorizonDays: aggressiveHorizonDays, LatenessDays: aggressiveMaxLatenessDays},
		{HorizonDays: lastResortHorizonDays, LatenessDays: lastResortMaxLatenessDays},
		{HorizonDays: maxHorizonDays, LatenessDays: maxMaxLatenessDays},
	}
}

func containsAnyReasonCode(reasons []string, reasonCode string) bool {
	for _, r := range reasons {
		if strings.Contains(strings.ToLower(r), strings.ToLower(reasonCode)) {
			return true
		}
	}
	return false
}

func placementRetryEligible(reasons []string) bool {
	if containsAnyReasonCode(reasons, "calendar_outside_shift") ||
		containsAnyReasonCode(reasons, "holiday_blocked") ||
		containsAnyReasonCode(reasons, "resource_calendar_blocked") ||
		containsAnyReasonCode(reasons, "overlap") ||
		containsAnyReasonCode(reasons, "precedence") {
		return false
	}
	return containsAnyReasonCode(reasons, "no feasible window") ||
		containsAnyReasonCode(reasons, "no_feasible_window") ||
		containsAnyReasonCode(reasons, "horizon_cap_reached")
}

func placementCapEnd(now, start, adaptiveEnd time.Time, horizonDays int) time.Time {
	capEnd := now.Add(time.Duration(horizonDays) * 24 * time.Hour)
	if adaptiveEnd.Before(capEnd) {
		capEnd = adaptiveEnd
	}
	if capEnd.Before(start) {
		return start
	}
	return capEnd
}

func placementCapEndHybrid(now, start, adaptiveEnd, effectiveDeadline time.Time, horizonDays int) time.Time {
	capEnd := now.Add(time.Duration(horizonDays) * 24 * time.Hour)
	if !effectiveDeadline.IsZero() {
		deadlineCap := effectiveDeadline.Add(time.Duration(hybridDeadlineBufferDays) * 24 * time.Hour)
		if deadlineCap.Before(capEnd) {
			capEnd = deadlineCap
		}
	}
	if adaptiveEnd.Before(capEnd) {
		capEnd = adaptiveEnd
	}
	if capEnd.Before(start) {
		return start
	}
	return capEnd
}

func classifyAttemptResult(reasons []string) machineAttemptResult {
	if containsAnyReasonCode(reasons, "calendar_outside_shift") ||
		containsAnyReasonCode(reasons, "holiday_blocked") ||
		containsAnyReasonCode(reasons, "resource_calendar_blocked") ||
		containsAnyReasonCode(reasons, "calendar") {
		return machineAttemptCalendar
	}
	if containsAnyReasonCode(reasons, "overlap") {
		return machineAttemptOverlap
	}
	if containsAnyReasonCode(reasons, "precedence") {
		return machineAttemptPrecedence
	}
	if containsAnyReasonCode(reasons, "no feasible window") ||
		containsAnyReasonCode(reasons, "no_feasible_window") ||
		containsAnyReasonCode(reasons, "horizon_cap_reached") {
		return machineAttemptNoWindow
	}
	return machineAttemptUnknown
}

func canonicalAttemptSignature(result machineAttemptResult, reasons []string) string {
	base := string(result)
	if len(reasons) == 0 {
		return base
	}
	first := strings.ToLower(strings.TrimSpace(reasons[0]))
	return base + "|" + first
}

func shouldEarlyExitIdenticalFailure(lastResult machineAttemptResult, lastSig string, currentResult machineAttemptResult, currentSig string, attemptedCount int, allowNoWindowEarlyExit bool) bool {
	if attemptedCount < minDistinctAttemptsForEarlyExit {
		return false
	}
	if currentResult == machineAttemptNoWindow && !allowNoWindowEarlyExit {
		return false
	}
	return currentResult == lastResult && currentSig == lastSig
}

func freeIntervalsFromWindows(workWindows, busy []BusyInterval, from, to time.Time, maxScan int) []BusyInterval {
	if !to.After(from) {
		return nil
	}
	if maxScan <= 0 {
		maxScan = len(workWindows)
	}
	if len(workWindows) > maxScan {
		workWindows = workWindows[:maxScan]
	}
	if len(busy) > 1 {
		sort.Slice(busy, func(i, j int) bool { return busy[i].Start.Before(busy[j].Start) })
		busy = mergeBusyIntervals(busy)
	}
	free := make([]BusyInterval, 0, len(workWindows))
	for _, w := range workWindows {
		ws := w.Start
		we := w.End
		if from.After(ws) {
			ws = from
		}
		if to.Before(we) {
			we = to
		}
		if !we.After(ws) {
			continue
		}
		cur := ws
		for _, b := range busy {
			if !b.End.After(cur) {
				continue
			}
			if !b.Start.Before(we) {
				break
			}
			if b.Start.After(cur) {
				free = append(free, BusyInterval{Start: cur, End: b.Start})
			}
			if b.End.After(cur) {
				cur = b.End
			}
			if !we.After(cur) {
				break
			}
		}
		if we.After(cur) {
			free = append(free, BusyInterval{Start: cur, End: we})
		}
	}
	sort.SliceStable(free, func(i, j int) bool {
		if free[i].Start.Equal(free[j].Start) {
			return free[i].End.Before(free[j].End)
		}
		return free[i].Start.Before(free[j].Start)
	})
	return free
}

func planSplitSlicesSameMachineGreedy(free []BusyInterval, required time.Duration) splitPlanResult {
	requiredMins := maxInt(int(required.Minutes()), 1)
	minSlice := time.Duration(minSliceMinutes) * time.Minute
	out := splitPlanResult{
		Slices:          make([]BusyInterval, 0, maxSlicesPerStep),
		RequiredMinutes: requiredMins,
	}
	if required <= 0 {
		out.Valid = true
		return out
	}
	remaining := required
	var prevEnd time.Time
	for _, iv := range free {
		if len(out.Slices) >= maxSlicesPerStep {
			break
		}
		win := iv.End.Sub(iv.Start)
		winMins := int(win.Minutes())
		if winMins > out.MaxContinuousWindowMins {
			out.MaxContinuousWindowMins = winMins
		}
		if !prevEnd.IsZero() && maxGapBetweenSlices >= 0 && iv.Start.Sub(prevEnd) > maxGapBetweenSlices {
			break
		}
		if win < minSlice {
			continue
		}
		take := win
		if remaining < take {
			take = remaining
		}
		// Avoid micro-fragmentation for incomplete non-final pieces.
		if take < minSlice && remaining > minSlice {
			continue
		}
		s := BusyInterval{Start: iv.Start, End: iv.Start.Add(take)}
		out.Slices = append(out.Slices, s)
		out.CoveredMinutes += int(take.Minutes())
		remaining -= take
		prevEnd = s.End
		if remaining <= 0 {
			break
		}
	}
	nonOverlap := true
	for i := 0; i+1 < len(out.Slices); i++ {
		if out.Slices[i].End.After(out.Slices[i+1].Start) {
			nonOverlap = false
			break
		}
	}
	out.Valid = remaining <= 0 && out.CoveredMinutes >= out.RequiredMinutes && len(out.Slices) <= maxSlicesPerStep && nonOverlap
	if !out.Valid {
		out.Reason = "split plan incomplete coverage under slice bounds"
	}
	return out
}

func planSplitSlicesCrossMachineGreedy(machineFree map[string][]BusyInterval, required time.Duration) ([]splitCandidateSlice, splitPlanResult) {
	requiredMins := maxInt(int(required.Minutes()), 1)
	minSlice := time.Duration(minSliceMinutes) * time.Minute
	out := splitPlanResult{
		Slices:          make([]BusyInterval, 0, maxSlicesPerStep),
		RequiredMinutes: requiredMins,
	}
	if required <= 0 {
		out.Valid = true
		return nil, out
	}
	candidates := make([]splitCandidateSlice, 0, 64)
	for machineID, free := range machineFree {
		for _, iv := range free {
			if iv.End.Sub(iv.Start) < minSlice {
				continue
			}
			candidates = append(candidates, splitCandidateSlice{MachineID: machineID, Interval: iv})
			winMins := int(iv.End.Sub(iv.Start).Minutes())
			if winMins > out.MaxContinuousWindowMins {
				out.MaxContinuousWindowMins = winMins
			}
		}
	}
	sort.SliceStable(candidates, func(i, j int) bool {
		if candidates[i].Interval.Start.Equal(candidates[j].Interval.Start) {
			if candidates[i].MachineID == candidates[j].MachineID {
				return candidates[i].Interval.End.Before(candidates[j].Interval.End)
			}
			return candidates[i].MachineID < candidates[j].MachineID
		}
		return candidates[i].Interval.Start.Before(candidates[j].Interval.Start)
	})
	remaining := required
	var prevEnd time.Time
	used := make([]splitCandidateSlice, 0, maxSlicesPerStep)
	for _, c := range candidates {
		if len(used) >= maxSlicesPerStep {
			break
		}
		if !prevEnd.IsZero() && maxGapBetweenSlices >= 0 && c.Interval.Start.Sub(prevEnd) > maxGapBetweenSlices {
			break
		}
		win := c.Interval.End.Sub(c.Interval.Start)
		take := win
		if remaining < take {
			take = remaining
		}
		if take < minSlice && remaining > minSlice {
			continue
		}
		s := BusyInterval{Start: c.Interval.Start, End: c.Interval.Start.Add(take)}
		out.Slices = append(out.Slices, s)
		used = append(used, splitCandidateSlice{MachineID: c.MachineID, Interval: s})
		out.CoveredMinutes += int(take.Minutes())
		remaining -= take
		prevEnd = s.End
		if remaining <= 0 {
			break
		}
	}
	nonOverlap := true
	for i := 0; i+1 < len(out.Slices); i++ {
		if out.Slices[i].End.After(out.Slices[i+1].Start) {
			nonOverlap = false
			break
		}
	}
	out.Valid = remaining <= 0 && out.CoveredMinutes >= out.RequiredMinutes && len(out.Slices) <= maxSlicesPerStep && nonOverlap
	if !out.Valid {
		out.Reason = "cross-machine split plan incomplete coverage under slice bounds"
	}
	return used, out
}

func allocateSplitSliceQuantities(total int, slices []BusyInterval) []int {
	if total <= 0 || len(slices) == 0 {
		return nil
	}
	totalMinutes := 0.0
	percentages := make([]float64, 0, len(slices))
	for _, sl := range slices {
		minutes := sl.End.Sub(sl.Start).Minutes()
		if minutes <= 0 {
			return nil
		}
		totalMinutes += minutes
		percentages = append(percentages, minutes)
	}
	if totalMinutes <= 0 {
		return nil
	}
	for i := range percentages {
		percentages[i] = percentages[i] * 100 / totalMinutes
	}
	allocations := allocateSplitQuantities(total, percentages, len(slices), 0)
	if len(allocations) != len(slices) {
		return nil
	}
	sum := 0
	for _, qty := range allocations {
		if qty <= 0 {
			return nil
		}
		sum += qty
	}
	if sum != total {
		return nil
	}
	return allocations
}

func cloneTentativeSlots(slots []TentativeSlot) []TentativeSlot {
	cp := make([]TentativeSlot, len(slots))
	copy(cp, slots)
	return cp
}

func attemptStrictPlacementTopK(
	svc *AIPredictiveService,
	in strictPlacementInput,
	attemptMachines []CandidateMachine,
) strictPlacementOutcome {
	outcome := strictPlacementOutcome{
		Attempts:            make([]strictPlacementAttempt, 0, len(attemptMachines)),
		AttemptedMachineIDs: make([]string, 0, len(attemptMachines)),
	}
	immutableTentative := cloneTentativeSlots(in.Tentative)
	if len(attemptMachines) > topKMachines {
		attemptMachines = attemptMachines[:topKMachines]
	}
	lastSig := ""
	lastResult := machineAttemptUnknown
	for _, machine := range attemptMachines {
		if outcome.AttemptedCount >= topKMachines {
			break
		}
		placementHorizonEnd := in.HorizonEnd
		expansions := 0
		var found bool
		var foundStart time.Time
		var reasons []string
		var diag map[string]interface{}
		for {
			foundStart, found, reasons, diag = svc.scheduling.findFeasibleMachineStart(
				in.JobStepID,
				machine.MachineID,
				in.ProcessStep,
				in.Start,
				in.Duration,
				maxInt(in.Quantity, 1),
				"",
				immutableTentative,
				nil,
				placementHorizonEnd,
			)
			if found || expansions >= in.MaxExpansions || !placementHorizonEnd.Before(in.HorizonEnd) {
				break
			}
			placementHorizonEnd = placementHorizonEnd.Add(in.GrowBy)
			if placementHorizonEnd.After(in.HorizonEnd) {
				placementHorizonEnd = in.HorizonEnd
			}
			expansions++
		}
		outcome.Expansions += expansions
		outcome.AttemptedCount++
		outcome.AttemptedMachineIDs = append(outcome.AttemptedMachineIDs, machine.MachineID)
		if found {
			outcome.Ok = true
			outcome.Start = foundStart
			outcome.Reasons = reasons
			outcome.Diag = diag
			outcome.SelectedMachineID = machine.MachineID
			return outcome
		}
		result := classifyAttemptResult(reasons)
		sig := canonicalAttemptSignature(result, reasons)
		if result == machineAttemptNoWindow {
			work := svc.scheduling.machineWorkWindows(machine.MachineID, in.Start, in.HorizonEnd)
			busy := svc.scheduling.machineBusyIntervals(machine.MachineID, immutableTentative)
			free := freeIntervalsFromWindows(work, busy, in.Start, in.HorizonEnd, maxIntervalsScannedPerMachine)
			splitPlan := planSplitSlicesSameMachineGreedy(free, in.Duration)
			if splitPlan.Valid {
				outcome.Ok = true
				outcome.Start = splitPlan.Slices[0].Start
				outcome.SelectedMachineID = machine.MachineID
				outcome.SplitUsed = true
				outcome.SplitSlices = splitPlan.Slices
				outcome.CoveredMinutes = splitPlan.CoveredMinutes
				outcome.RequiredMinutes = splitPlan.RequiredMinutes
				outcome.MaxContinuousWindowMins = splitPlan.MaxContinuousWindowMins
				return outcome
			}
			if splitPlan.Reason != "" {
				reasons = append(reasons, splitPlan.Reason)
			}
			// Cross-machine fallback: deterministic earliest-first packing across attempted machines.
			multiFree := map[string][]BusyInterval{}
			for _, c := range attemptMachines {
				workW := svc.scheduling.machineWorkWindows(c.MachineID, in.Start, in.HorizonEnd)
				busyW := svc.scheduling.machineBusyIntervals(c.MachineID, immutableTentative)
				multiFree[c.MachineID] = freeIntervalsFromWindows(workW, busyW, in.Start, in.HorizonEnd, maxIntervalsScannedPerMachine)
			}
			used, crossPlan := planSplitSlicesCrossMachineGreedy(multiFree, in.Duration)
			if crossPlan.Valid && len(used) > 0 {
				outcome.Ok = true
				outcome.Start = used[0].Interval.Start
				outcome.SelectedMachineID = used[0].MachineID
				outcome.SplitUsed = true
				outcome.SplitSlices = make([]BusyInterval, 0, len(used))
				outcome.SplitMachineIDs = make([]string, 0, len(used))
				for _, u := range used {
					outcome.SplitSlices = append(outcome.SplitSlices, u.Interval)
					outcome.SplitMachineIDs = append(outcome.SplitMachineIDs, u.MachineID)
				}
				outcome.CoveredMinutes = crossPlan.CoveredMinutes
				outcome.RequiredMinutes = crossPlan.RequiredMinutes
				outcome.MaxContinuousWindowMins = crossPlan.MaxContinuousWindowMins
				return outcome
			}
			if crossPlan.Reason != "" {
				reasons = append(reasons, crossPlan.Reason)
			}
		}
		outcome.Attempts = append(outcome.Attempts, strictPlacementAttempt{
			MachineID: machine.MachineID,
			Result:    result,
			Signature: sig,
		})
		outcome.Reasons = reasons
		outcome.Diag = diag
		// Early exit when structural failure signature repeats across attempts.
		if shouldEarlyExitIdenticalFailure(lastResult, lastSig, result, sig, outcome.AttemptedCount, in.AllowNoWindowEarlyExit) {
			outcome.EarlyExit = true
			outcome.EarlyExitSignature = sig
			return outcome
		}
		lastSig = sig
		lastResult = result
	}
	return outcome
}

type candidateTierScore struct {
	latenessClass int
	setupCost     int
	negativeSlack float64
}

func chooseTieredCandidate(candidates []CandidateMachine, duration time.Duration, stepCursor time.Time, targetCompletion *time.Time, jobDeadline time.Time, lastMachineID string) (CandidateMachine, candidateTierScore) {
	best := candidates[0]
	bestScore := candidateTierScore{latenessClass: 3, setupCost: int(^uint(0) >> 1), negativeSlack: math.MaxFloat64}
	for _, c := range candidates {
		start := stepCursor
		if c.AvailableFrom.After(start) {
			start = c.AvailableFrom
		}
		finish := start.Add(duration)
		target := jobDeadline
		if targetCompletion != nil && !targetCompletion.IsZero() {
			target = *targetCompletion
		}
		latenessClass := 0
		if finish.After(target) {
			delay := finish.Sub(target)
			switch {
			case delay <= 30*time.Minute:
				latenessClass = 1
			case delay <= 2*time.Hour:
				latenessClass = 2
			default:
				latenessClass = 3
			}
		}
		setupCost := 1
		if lastMachineID == "" || lastMachineID == c.MachineID {
			setupCost = 0
		}
		slack := target.Sub(finish).Minutes()
		score := candidateTierScore{
			latenessClass: latenessClass,
			setupCost:     setupCost,
			negativeSlack: -slack,
		}
		if score.latenessClass < bestScore.latenessClass ||
			(score.latenessClass == bestScore.latenessClass && score.setupCost < bestScore.setupCost) ||
			(score.latenessClass == bestScore.latenessClass && score.setupCost == bestScore.setupCost && score.negativeSlack < bestScore.negativeSlack) ||
			(score.latenessClass == bestScore.latenessClass && score.setupCost == bestScore.setupCost && score.negativeSlack == bestScore.negativeSlack && (c.MachineID < best.MachineID ||
				(c.MachineID == best.MachineID && c.AvailableFrom.Before(best.AvailableFrom)))) {
			best = c
			bestScore = score
		}
	}
	return best, bestScore
}

func computeAdaptiveHorizonEnd(now time.Time, deadline time.Time, targetCompletion *time.Time, cursor time.Time, hp horizonPolicy) time.Time {
	base := now.Add(hp.rollingWindow)
	if cursor.After(now) && cursor.Add(hp.rollingWindow).After(base) {
		base = cursor.Add(hp.rollingWindow)
	}
	if !deadline.IsZero() && deadline.Add(24*time.Hour).After(base) {
		base = deadline.Add(24 * time.Hour)
	}
	if targetCompletion != nil && targetCompletion.Add(24*time.Hour).After(base) {
		base = targetCompletion.Add(24 * time.Hour)
	}
	capEnd := now.Add(hp.absoluteCap)
	if base.After(capEnd) {
		return capEnd
	}
	return base
}

func topKByEarliestFinish(candidates []CandidateMachine, duration time.Duration, stepCursor time.Time, k int) []CandidateMachine {
	cp := make([]CandidateMachine, len(candidates))
	copy(cp, candidates)
	sort.SliceStable(cp, func(i, j int) bool {
		is := stepCursor
		if cp[i].AvailableFrom.After(is) {
			is = cp[i].AvailableFrom
		}
		js := stepCursor
		if cp[j].AvailableFrom.After(js) {
			js = cp[j].AvailableFrom
		}
		if !is.Add(duration).Equal(js.Add(duration)) {
			return is.Add(duration).Before(js.Add(duration))
		}
		if cp[i].MachineID != cp[j].MachineID {
			return cp[i].MachineID < cp[j].MachineID
		}
		return is.Before(js)
	})
	if k <= 0 || k > len(cp) {
		k = len(cp)
	}
	return cp[:k]
}

func generateWithCandidateSort(
	ctx context.Context,
	svc *AIPredictiveService,
	job *domain.Job,
	preview *SolverPreview,
	tentativeSlots []TentativeSlot,
	targetCompletion *time.Time,
	h *heuristicContext,
	engineVersion string,
	sorter candidateSorter,
) (*SchedulingProposal, error) {
	return generateWithCandidateSortPick(ctx, svc, job, preview, tentativeSlots, targetCompletion, h, engineVersion, sorter, 0, 0, 0)
}

func generateWithCandidateSortPick(
	ctx context.Context,
	svc *AIPredictiveService,
	job *domain.Job,
	preview *SolverPreview,
	tentativeSlots []TentativeSlot,
	targetCompletion *time.Time,
	h *heuristicContext,
	engineVersion string,
	sorter candidateSorter,
	pickIndex int,
	cursorOffset time.Duration,
	stepStartOffset time.Duration,
) (*SchedulingProposal, error) {
	now := time.Now()
	p := buildBaseProposal(job, "v2/"+engineVersion, now)
	cursor := now
	if preview != nil && preview.EarliestReadyAt != nil && preview.EarliestReadyAt.After(cursor) {
		cursor = *preview.EarliestReadyAt
	}
	if cursorOffset > 0 {
		cursor = cursor.Add(cursorOffset)
	}
	p.EarliestStart = cursor
	hp := defaultHorizonPolicy()
	lastMachineID := ""

	for _, step := range preview.Steps {
		select {
		case <-ctx.Done():
			p.Feasible = false
			p.BlockedReasons = append(p.BlockedReasons, "Heuristic time budget exceeded.")
			finalizeProposalScores(p, job)
			return p, nil
		default:
		}

		ct := combinedTentative(tentativeSlots, p.ProposedSlots)
		stepCursor := cursor
		if stepStartOffset > 0 {
			stepCursor = stepCursor.Add(stepStartOffset)
		}
		adaptiveEnd := computeAdaptiveHorizonEnd(now, job.Deadline, targetCompletion, stepCursor, hp)
		candidates, err := h.candidatesWithCache(svc, step.JobStepID, stepCursor, adaptiveEnd, ct)
		expanded := 0
		for (err != nil || len(filterAvailableCandidates(candidates)) == 0) && expanded < hp.maxExpansions && adaptiveEnd.Before(now.Add(hp.absoluteCap)) {
			adaptiveEnd = adaptiveEnd.Add(hp.growBy)
			capEnd := now.Add(hp.absoluteCap)
			if adaptiveEnd.After(capEnd) {
				adaptiveEnd = capEnd
			}
			expanded++
			candidates, err = h.candidatesWithCache(svc, step.JobStepID, stepCursor, adaptiveEnd, ct)
		}
		if err != nil {
			p.Feasible = false
			p.BlockedReasons = append(p.BlockedReasons, fmt.Sprintf("Failed to fetch candidates for step %s: %v", step.StepName, err))
			continue
		}
		processStep, _ := svc.scheduling.GetProcessStepForJobStep(step.JobStepID)
		if processStep == nil {
			processStep = &domain.ProcessSteps{DefaultProcessingTime: maxInt(step.EstimatedDurationMins, 1)}
		}
		stepDuration := estimatedStepDuration(*processStep, candidates, float64(step.QuantityTarget))
		candidates, err = h.candidatesWithCache(svc, step.JobStepID, stepCursor, adaptiveEnd, ct)
		if err != nil {
			p.Feasible = false
			p.BlockedReasons = append(p.BlockedReasons, fmt.Sprintf("Failed to fetch candidates for step %s: %v", step.StepName, err))
			continue
		}
		available := filterAvailableCandidates(candidates)
		if len(available) == 0 {
			p.Feasible = false
			p.BlockedReasons = append(p.BlockedReasons, fmt.Sprintf("reason_code=horizon_cap_reached no feasible window for step %s within horizon (expanded_steps=%d, horizon_end=%s).", step.StepName, expanded, adaptiveEnd.UTC().Format(time.RFC3339)))
			continue
		}

		// Keep existing parallel split behavior (fast) for now.
		suggestion, _ := svc.SuggestSplit(step.JobStepID)
		if suggestion != nil && suggestion.IsParallel && suggestion.RecommendedSplits > 1 {
			parallelCount := suggestion.RecommendedSplits
			if parallelCount > len(available) {
				parallelCount = len(available)
			}
			group := available[:parallelCount]
			groupStart := stepCursor
			for _, c := range group {
				if c.AvailableFrom.After(groupStart) {
					groupStart = c.AvailableFrom
				}
			}
			duration := estimatedStepDuration(domain.ProcessSteps{
				DefaultPreparationTime: 0,
				DefaultProcessingTime:  maxInt(step.EstimatedDurationMins, 1),
				DefaultCleaningTime:    0,
				DefaultChangeoverTime:  0,
			}, group, float64(step.QuantityTarget))
			allocations := allocateSplitQuantities(step.QuantityTarget, suggestion.AllocationPercents, parallelCount, step.MinBatchSize)
			groupEnd := groupStart
			for i := 0; i < parallelCount; i++ {
				end := groupStart.Add(duration)
				if end.After(groupEnd) {
					groupEnd = end
				}
				p.ProposedSlots = append(p.ProposedSlots, ProposedSlot{
					JobStepID:             step.JobStepID,
					StepID:                step.StepID,
					StepName:              step.StepName,
					MachineID:             group[i].MachineID,
					MachineName:           group[i].MachineName,
					ScheduledStart:        groupStart,
					ScheduledEnd:          end,
					QuantityPlanned:       allocations[i],
					AllocationPercent:     suggestion.AllocationPercents[minInt(i, len(suggestion.AllocationPercents)-1)],
					IsParallel:            true,
					BatchSequence:         i + 1,
					EstimatedDurationMins: int(duration.Minutes()),
					Reasoning: []string{
						"Parallel split was chosen because the step allows parallel execution.",
						fmt.Sprintf("Machine %s is one of the best currently feasible candidates.", group[i].MachineName),
					},
				})
			}
			cursor = groupEnd
			cursor = cursor.Add(time.Duration(step.MinWaitMinutes+step.TransferMinutes) * time.Minute)
			p.Summary = append(p.Summary, fmt.Sprintf("Step %s was split across %d machines.", step.StepName, parallelCount))
			continue
		}

		sorter(step, stepDuration, available)
		candidatePool := topKByEarliestFinish(available, stepDuration, stepCursor, maxInt(topKMachines*2, 8))
		best := candidatePool[0]
		if pickIndex > 0 && pickIndex < len(available) {
			best = available[pickIndex]
		}
		bestTiered, tier := chooseTieredCandidate(candidatePool, stepDuration, stepCursor, targetCompletion, job.Deadline, lastMachineID)
		best = bestTiered
		start := stepCursor
		if best.AvailableFrom.After(start) {
			start = best.AvailableFrom
		}
		attemptMachines := make([]CandidateMachine, 0, topKMachines)
		attemptMachines = append(attemptMachines, best)
		for _, c := range candidatePool {
			if len(attemptMachines) >= topKMachines {
				break
			}
			if c.MachineID == best.MachineID {
				continue
			}
			attemptMachines = append(attemptMachines, c)
		}
		primaryCap := placementCapEndHybrid(now, start, adaptiveEnd, job.Deadline, primaryHorizonDays)
		placementInput := strictPlacementInput{
			JobStepID:              step.JobStepID,
			Start:                  start,
			Duration:               stepDuration,
			Quantity:               step.QuantityTarget,
			ProcessStep:            processStep,
			Tentative:              ct,
			HorizonEnd:             primaryCap,
			MaxExpansions:          hp.maxExpansions,
			GrowBy:                 hp.growBy,
			AllowNoWindowEarlyExit: false,
		}
		outcome := strictPlacementOutcome{}
		stagesTried := 0
		placementMode := "strict"
		finalReason := ""
		placementExpansions := 0
		horizonEndUsed := primaryCap
		for idx, st := range placementStages() {
			effectiveDeadline := job.Deadline.Add(time.Duration(st.LatenessDays) * 24 * time.Hour)
			stageAdaptive := computeAdaptiveHorizonEnd(now, effectiveDeadline, targetCompletion, stepCursor, hp)
			stageCap := placementCapEndHybrid(now, start, stageAdaptive, effectiveDeadline, st.HorizonDays)
			stageInput := placementInput
			stageInput.HorizonEnd = stageCap
			// No-window signature early-exit only on final stage.
			stageInput.AllowNoWindowEarlyExit = idx == len(placementStages())-1
			stageOutcome := attemptStrictPlacementTopK(svc, stageInput, attemptMachines)
			placementExpansions += stageOutcome.Expansions
			horizonEndUsed = stageCap
			stagesTried = idx + 1
			if stageOutcome.Ok || !placementRetryEligible(stageOutcome.Reasons) {
				outcome = stageOutcome
				break
			}
			outcome = stageOutcome
		}
		if outcome.Ok {
			if stagesTried == 1 {
				placementMode = "strict"
			} else {
				placementMode = "relaxed"
			}
		}
		if !outcome.Ok {
			p.Feasible = false
			reason := "reason_code=no_feasible_window failed strict feasible placement"
			if len(outcome.Reasons) > 0 {
				reason += ": " + outcome.Reasons[0]
				finalReason = outcome.Reasons[0]
			}
			reason += fmt.Sprintf(" (placement_expanded_steps=%d, horizon_end=%s)", placementExpansions, horizonEndUsed.UTC().Format(time.RFC3339))
			reason += fmt.Sprintf(" (stages_tried=%d, cap_anchor=hybrid)", stagesTried)
			p.BlockedReasons = append(p.BlockedReasons, reason)
			logger.L().Warn("proposal_stage_generation_no_feasible_window",
				zap.String("job_id", job.JobID),
				zap.String("job_step_id", step.JobStepID),
				zap.String("machine_id", best.MachineID),
				zap.Int("stages_tried", stagesTried),
				zap.String("placement_mode", placementMode),
				zap.Int("primary_horizon_days", primaryHorizonDays),
				zap.Int("max_horizon_days", maxHorizonDays),
				zap.String("final_reason", finalReason),
				zap.Strings("attempted_machine_ids", outcome.AttemptedMachineIDs),
				zap.Int("attempted_count", outcome.AttemptedCount),
				zap.Bool("early_exit", outcome.EarlyExit),
				zap.String("early_exit_signature", outcome.EarlyExitSignature),
				zap.String("selected_machine_id", outcome.SelectedMachineID),
				zap.Any("attempts", outcome.Attempts),
				zap.Any("diagnostics", outcome.Diag),
			)
			continue
		}
		if stagesTried > 1 && outcome.Ok {
			logger.L().Info("proposal_stage_generation_retry_result",
				zap.String("job_id", job.JobID),
				zap.String("job_step_id", step.JobStepID),
				zap.Int("stages_tried", stagesTried),
				zap.String("placement_mode", placementMode),
				zap.Int("primary_horizon_days", primaryHorizonDays),
				zap.Int("max_horizon_days", maxHorizonDays),
				zap.String("result", "feasible"),
				zap.String("final_reason", ""),
				zap.Strings("attempted_machine_ids", outcome.AttemptedMachineIDs),
				zap.Int("attempted_count", outcome.AttemptedCount),
				zap.Bool("early_exit", outcome.EarlyExit),
				zap.String("selected_machine_id", outcome.SelectedMachineID),
				zap.Any("attempts", outcome.Attempts),
			)
		}
		start = outcome.Start
		if outcome.SelectedMachineID != "" {
			for _, c := range candidatePool {
				if c.MachineID == outcome.SelectedMachineID {
					best = c
					break
				}
			}
		}
		end := start.Add(stepDuration)
		if outcome.SplitUsed && len(outcome.SplitSlices) > 0 {
			end = outcome.SplitSlices[len(outcome.SplitSlices)-1].End
		}
		logger.L().Info("proposal_stage_generation",
			zap.String("job_id", job.JobID),
			zap.String("job_step_id", step.JobStepID),
			zap.String("machine_id", best.MachineID),
			zap.String("scheduled_start", start.In(time.Local).Format(time.RFC3339)),
			zap.String("scheduled_end", end.In(time.Local).Format(time.RFC3339)),
			zap.Int("expanded_steps", expanded),
			zap.Bool("split_fallback_used", outcome.SplitUsed),
			zap.Int("slice_count", len(outcome.SplitSlices)),
			zap.Int("covered_minutes", outcome.CoveredMinutes),
			zap.Int("required_minutes", outcome.RequiredMinutes),
			zap.Int("max_continuous_window_minutes", outcome.MaxContinuousWindowMins),
		)
		if outcome.SplitUsed && len(outcome.SplitSlices) > 0 {
			allocations := allocateSplitSliceQuantities(step.QuantityTarget, outcome.SplitSlices)
			if len(allocations) != len(outcome.SplitSlices) {
				p.Feasible = false
				p.BlockedReasons = append(p.BlockedReasons, fmt.Sprintf("reason_code=invalid_split_quantity split fallback for step %s cannot allocate valid slice quantities within batch/split limits.", step.StepName))
				continue
			}
			for idx, sl := range outcome.SplitSlices {
				splitMachineID := best.MachineID
				splitMachineName := best.MachineName
				if idx < len(outcome.SplitMachineIDs) && outcome.SplitMachineIDs[idx] != "" {
					splitMachineID = outcome.SplitMachineIDs[idx]
					for _, c := range available {
						if c.MachineID == splitMachineID {
							splitMachineName = c.MachineName
							break
						}
					}
				}
				p.ProposedSlots = append(p.ProposedSlots, ProposedSlot{
					JobStepID:             step.JobStepID,
					StepID:                step.StepID,
					StepName:              step.StepName,
					MachineID:             splitMachineID,
					MachineName:           splitMachineName,
					ScheduledStart:        sl.Start,
					ScheduledEnd:          sl.End,
					QuantityPlanned:       allocations[idx],
					AllocationPercent:     mathRound(float64(allocations[idx])*100/float64(step.QuantityTarget), 2),
					IsParallel:            false,
					BatchSequence:         idx + 1,
					EstimatedDurationMins: maxInt(int(sl.End.Sub(sl.Start).Minutes()), 1),
					Reasoning: []string{
						fmt.Sprintf("Selected machine %s via strategy %s.", splitMachineName, engineVersion),
						"Split fallback used after no continuous window found.",
						fmt.Sprintf("Tiered score: lateness_class=%d setup_switch=%d slack_rank=%.1f", tier.latenessClass, tier.setupCost, tier.negativeSlack),
						fmt.Sprintf("Horizon diagnostics: expanded_steps=%d horizon_end=%s", expanded, adaptiveEnd.UTC().Format(time.RFC3339)),
					},
				})
			}
		} else {
			p.ProposedSlots = append(p.ProposedSlots, ProposedSlot{
				JobStepID:             step.JobStepID,
				StepID:                step.StepID,
				StepName:              step.StepName,
				MachineID:             best.MachineID,
				MachineName:           best.MachineName,
				ScheduledStart:        start,
				ScheduledEnd:          end,
				QuantityPlanned:       step.QuantityTarget,
				AllocationPercent:     100,
				IsParallel:            false,
				BatchSequence:         1,
				EstimatedDurationMins: maxInt(int(stepDuration.Minutes()), 1),
				Reasoning: []string{
					fmt.Sprintf("Selected machine %s via strategy %s.", best.MachineName, engineVersion),
					fmt.Sprintf("Tiered score: lateness_class=%d setup_switch=%d slack_rank=%.1f", tier.latenessClass, tier.setupCost, tier.negativeSlack),
					fmt.Sprintf("Horizon diagnostics: expanded_steps=%d horizon_end=%s", expanded, adaptiveEnd.UTC().Format(time.RFC3339)),
				},
			})
		}
		lastMachineID = best.MachineID
		cursor = end
		cursor = cursor.Add(time.Duration(step.MinWaitMinutes+step.TransferMinutes) * time.Minute)
		p.Summary = append(p.Summary, fmt.Sprintf("Step %s was assigned to %s.", step.StepName, best.MachineName))
	}

	finalizeProposalScores(p, job)
	return p, nil
}

func sortByEarliestFinish(targetCompletion *time.Time) candidateSorter {
	return func(step SolverPreviewStep, duration time.Duration, candidates []CandidateMachine) {
		sort.SliceStable(candidates, func(i, j int) bool {
			iFinish := candidates[i].AvailableFrom.Add(duration)
			jFinish := candidates[j].AvailableFrom.Add(duration)
			if targetCompletion != nil {
				// bias to finish earlier when target exists
				if !iFinish.Equal(jFinish) {
					return iFinish.Before(jFinish)
				}
			}
			if !iFinish.Equal(jFinish) {
				return iFinish.Before(jFinish)
			}
			if candidates[i].EfficiencyFactor != candidates[j].EfficiencyFactor {
				return candidates[i].EfficiencyFactor > candidates[j].EfficiencyFactor
			}
			return candidates[i].CapacityPerHour > candidates[j].CapacityPerHour
		})
	}
}

func sortByEarliestStart() candidateSorter {
	return func(_ SolverPreviewStep, _ time.Duration, candidates []CandidateMachine) {
		sort.SliceStable(candidates, func(i, j int) bool {
			if !candidates[i].AvailableFrom.Equal(candidates[j].AvailableFrom) {
				return candidates[i].AvailableFrom.Before(candidates[j].AvailableFrom)
			}
			if candidates[i].EfficiencyFactor != candidates[j].EfficiencyFactor {
				return candidates[i].EfficiencyFactor > candidates[j].EfficiencyFactor
			}
			return candidates[i].CapacityPerHour > candidates[j].CapacityPerHour
		})
	}
}

func sortByLeastLoaded(load map[string]float64) candidateSorter {
	return func(_ SolverPreviewStep, _ time.Duration, candidates []CandidateMachine) {
		sort.SliceStable(candidates, func(i, j int) bool {
			li := load[candidates[i].MachineID]
			lj := load[candidates[j].MachineID]
			if li != lj {
				return li < lj
			}
			if candidates[i].EfficiencyFactor != candidates[j].EfficiencyFactor {
				return candidates[i].EfficiencyFactor > candidates[j].EfficiencyFactor
			}
			return candidates[i].CapacityPerHour > candidates[j].CapacityPerHour
		})
	}
}

func sortByDeadlineBiased(targetCompletion *time.Time) candidateSorter {
	return func(_ SolverPreviewStep, duration time.Duration, candidates []CandidateMachine) {
		sort.SliceStable(candidates, func(i, j int) bool {
			iFinish := candidates[i].AvailableFrom.Add(duration)
			jFinish := candidates[j].AvailableFrom.Add(duration)
			if targetCompletion != nil {
				iMeets := !iFinish.After(*targetCompletion)
				jMeets := !jFinish.After(*targetCompletion)
				if iMeets != jMeets {
					return iMeets
				}
			}
			if !iFinish.Equal(jFinish) {
				return iFinish.Before(jFinish)
			}
			return candidates[i].EfficiencyFactor > candidates[j].EfficiencyFactor
		})
	}
}
